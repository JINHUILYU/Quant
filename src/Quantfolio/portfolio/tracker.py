from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from Quantfolio.config import QuantfolioConfig
from Quantfolio.portfolio.models import Holding, PortfolioSummary, Transaction

logger = logging.getLogger(__name__)


def _pnl_str(val: float) -> str:
    """Color-coded P&L string for HTML annotations."""
    color = "green" if val >= 0 else "red"
    return f'<span style="color:{color}">¥{val:+,.2f}</span>'


# ── NAV cache ────────────────────────────────────────────────────────────

class NavCache:
    """Local NAV cache — stores fetched data and only merges new dates.

    Avoids re-fetching full history from akshare every time: on first run
    it fetches everything, then on subsequent runs it only requests what's
    new since the last cached date.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, product_code: str) -> Path:
        return self.cache_dir / f"{product_code}.csv"

    def load(self, product_code: str) -> pd.DataFrame | None:
        """Read cached NAV, or None if no cache exists."""
        p = self._cache_path(product_code)
        if not p.exists():
            return None
        df = pd.read_csv(p, parse_dates=["date"])
        if df.empty:
            return None
        return df.sort_values("date").reset_index(drop=True)

    def save(self, product_code: str, df: pd.DataFrame) -> None:
        df = df.sort_values("date").reset_index(drop=True)
        df.to_csv(self._cache_path(product_code), index=False)

    def fetch(self, product_code: str, force_refresh: bool = False) -> pd.DataFrame:
        """Get NAV data, merging cache with any new data from akshare.

        When *force_refresh* is False and today's data is already cached,
        returns cached data without network call.
        """
        import akshare as ak

        cached = None if force_refresh else self.load(product_code)

        if cached is not None and not cached.empty:
            last_cached = cached["date"].max()
            today = pd.Timestamp.now().normalize()
            if last_cached.date() >= today.date():
                return cached  # up to date — no network call

        # Fetch full history (akshare doesn't support date-range filter)
        raw = ak.fund_open_fund_info_em(symbol=product_code, indicator="单位净值走势")
        new = raw.rename(columns={"净值日期": "date", "单位净值": "nav"})
        new["date"] = pd.to_datetime(new["date"])
        new = new[["date", "nav"]].sort_values("date").reset_index(drop=True)

        if cached is not None and not cached.empty:
            merged = pd.concat([cached, new], ignore_index=True)
            merged = merged.drop_duplicates(subset=["date"], keep="last")
            merged = merged.sort_values("date").reset_index(drop=True)
        else:
            merged = new

        self.save(product_code, merged)
        return merged


# ── Portfolio tracker ───────────────────────────────────────────────────


class PortfolioTracker:
    """Portfolio analysis for Chinese fund transactions.

    Loads transaction CSVs from data/portfolio/, fetches NAV via akshare,
    computes holdings, P&L, drawdown, and XIRR.
    """

    def __init__(self, config: QuantfolioConfig | None = None):
        self.cfg = config or QuantfolioConfig()
        self._nav_cache = NavCache(self.cfg.data_dir_abs.parent / "nav_cache")

    @property
    def portfolio_dir(self) -> Path:
        if hasattr(self, '_portfolio_dir') and self._portfolio_dir is not None:
            return self._portfolio_dir
        p = self.cfg.portfolio_dir_abs
        p.mkdir(parents=True, exist_ok=True)
        self._portfolio_dir = p
        return p

    def _path(self, product_code: str) -> Path:
        return self.portfolio_dir / f"{product_code}.csv"

    # ── CSV loading ────────────────────────────────────────────────────

    def save_template(self) -> Path:
        path = self.portfolio_dir / "template.csv"
        df = pd.DataFrame([{
            "date": "2024-01-15",
            "product": "002611",
            "type": "buy",
            "amount": 1000.00,
            "price": 1.2000,
            "shares": 832.50,
            "fee": 1.00,
            "notes": "定投",
        }])
        df.to_csv(path, index=False)
        logger.info("Template saved to %s", path)
        return path

    def load_transactions(self, product_code: str) -> list[Transaction]:
        path = self._path(product_code)
        if not path.exists():
            raise FileNotFoundError(
                f"No portfolio data for {product_code}. "
                f"Create {path} using template at {self.portfolio_dir / 'template.csv'}"
            )

        df = pd.read_csv(path, parse_dates=["date"])

        required = {"date", "product", "type", "amount", "price", "shares", "fee"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns in {path}: {missing}")

        invalid = df[~df["type"].isin(["buy", "sell", "dividend"])]
        if not invalid.empty:
            raise ValueError(
                f"Invalid type values at rows {invalid.index.tolist()}: "
                f"must be 'buy', 'sell', or 'dividend'"
            )

        transactions = []
        for _, row in df.iterrows():
            txn_type = str(row["type"])
            if txn_type == "dividend":
                transactions.append(Transaction(
                    date=row["date"],
                    product=str(row["product"]),
                    type="dividend",
                    amount=float(row.get("amount", 0) or 0),
                    price=float(row.get("price", 0) or 0),
                    shares=float(row.get("shares", 0) or 0),
                    fee=0.0,
                    notes=str(row.get("notes", "") or ""),
                ))
            else:
                price = row.get("price")
                shares = row.get("shares")
                # Skip incomplete rows (NAV not yet filled) so they don't
                # corrupt cost-basis / share-count calculations.
                if pd.isna(price) or pd.isna(shares) or price == 0:
                    continue
                transactions.append(Transaction(
                    date=row["date"],
                    product=str(row["product"]),
                    type=txn_type,
                    amount=float(row["amount"]),
                    price=float(price),
                    shares=float(shares),
                    fee=float(row.get("fee", 0.0) or 0.0),
                    notes=str(row.get("notes", "") or ""),
                ))
        return transactions

    # ── NAV fetching ───────────────────────────────────────────────────

    def fetch_nav(self, product_code: str, force_refresh: bool = False) -> pd.DataFrame:
        """Get NAV history for *product_code*, using local cache.

        On first call fetches full history from akshare and caches it.
        Subsequent calls return cached data unless *force_refresh* is True
        or new dates are available.
        """
        return self._nav_cache.fetch(product_code, force_refresh=force_refresh)

    # ── Core analysis ──────────────────────────────────────────────────

    def compute_daily_value(
        self,
        transactions: list[Transaction],
        nav_history: pd.DataFrame,
    ) -> pd.DataFrame:
        """Build daily portfolio value timeline using average-cost method."""
        txns = sorted(transactions, key=lambda t: t.date)

        start = min(txns[0].date, nav_history["date"].min())
        end = max(txns[-1].date, nav_history["date"].max())
        cal = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})

        daily = cal.merge(nav_history, on="date", how="left")
        daily["nav"] = daily["nav"].ffill()

        shares = 0.0
        total_cost = 0.0
        cum_invested = 0.0
        shares_arr = np.full(len(daily), np.nan)
        cost_arr = np.full(len(daily), np.nan)
        invested_arr = np.full(len(daily), np.nan)
        date_arr = daily["date"].values

        txn_idx = 0
        for i in range(len(daily)):
            while txn_idx < len(txns) and txns[txn_idx].date == date_arr[i]:
                t = txns[txn_idx]
                if t.type == "buy":
                    shares += t.shares
                    total_cost += t.amount
                    cum_invested += t.amount
                elif t.type == "dividend":
                    if t.shares > 0:
                        # 红利再投资：免费增加份额，成本不变
                        shares += t.shares
                    else:
                        # 现金分红：成本基准降低（相当于返还部分本金）
                        total_cost = max(0, total_cost - t.amount)
                        cum_invested -= t.amount
                else:  # sell
                    if shares > 0:
                        cost_reduction = total_cost * (t.shares / shares)
                        total_cost -= cost_reduction
                    shares -= t.shares
                    cum_invested -= t.amount
                    if shares < 0:
                        shares = 0.0
                        total_cost = 0.0
                txn_idx += 1

            shares_arr[i] = shares
            cost_arr[i] = total_cost
            invested_arr[i] = cum_invested

        daily["shares_held"] = shares_arr
        daily["total_cost"] = cost_arr
        daily["cumulative_invested"] = invested_arr
        daily["market_value"] = daily["shares_held"] * daily["nav"]
        daily["market_value"] = daily["market_value"].fillna(0.0)
        daily["unrealized_pnl"] = daily["market_value"] - daily["total_cost"]
        daily["unrealized_pnl_pct"] = np.where(
            daily["total_cost"] > 0,
            (daily["market_value"] / daily["total_cost"] - 1) * 100,
            0.0,
        )

        return daily

    def compute_holdings(
        self,
        daily_value: pd.DataFrame,
        product: str,
    ) -> list[Holding]:
        last = daily_value.iloc[-1]
        shares = last["shares_held"]
        cost = last["total_cost"]
        nav = last["nav"]
        mkt_val = last["market_value"]

        if shares > 0:
            avg_cost = cost / shares if cost > 0 else 0.0
            pnl = mkt_val - cost
            pnl_pct = (mkt_val / cost - 1) * 100 if cost > 0 else 0.0
        else:
            avg_cost = 0.0
            pnl = 0.0
            pnl_pct = 0.0

        avg_cost_r = round(avg_cost, 4)
        return [
            Holding(
                product=product,
                total_shares=round(shares, 2),
                avg_cost=avg_cost_r,
                current_price=round(nav, 4) if not pd.isna(nav) else 0.0,
                market_value=round(mkt_val, 2),
                cost_basis=round(shares * avg_cost_r, 2),
                unrealized_pnl=round(pnl, 2),
                unrealized_pnl_pct=round(pnl_pct, 2),
            ),
        ]

    @staticmethod
    def compute_xirr(
        transactions: list[Transaction],
        current_value: float,
        current_date: pd.Timestamp,
        guess: float = 0.05,
    ) -> float:
        """Annualized XIRR via Newton's method.

        Buys are negative cash flows, sells are positive, current value
        is a positive terminal cash flow. Returns annualized percentage.

        Returns 0.0 when holding period < 90 days (XIRR unreliable for
        very short periods due to aggressive annualization).
        """
        flows: list[tuple[pd.Timestamp, float]] = []
        for t in transactions:
            if t.type == "buy":
                flows.append((t.date, -t.amount))
            else:
                flows.append((t.date, t.amount))
        flows.append((current_date, current_value))
        flows.sort(key=lambda x: x[0])

        first_date = flows[0][0]
        total_days = (current_date - first_date).days
        if total_days < 90:
            return 0.0  # too short for meaningful annualization

        times = [(d - first_date).days / 365.0 for d, _ in flows]
        amounts = [cf for _, cf in flows]

        # Check if all flows have the same sign
        positives = sum(1 for a in amounts if a > 0)
        negatives = sum(1 for a in amounts if a < 0)
        if positives == 0 or negatives == 0:
            return 0.0

        rate = guess
        for _ in range(200):
            npv = 0.0
            dnpv = 0.0
            for cf, t in zip(amounts, times):
                if t == 0:
                    npv += cf
                    continue
                denom = (1.0 + rate) ** t
                npv += cf / denom
                dnpv += -cf * t / ((1.0 + rate) ** (t + 1.0))

            if abs(npv) < 1e-7:
                break

            if dnpv == 0.0:
                break

            rate -= npv / dnpv
            if rate < -0.999:
                rate = -0.999
            elif rate > 10.0:
                rate = 10.0
        else:
            # Newton didn't converge
            logger.warning("XIRR did not converge; returning 0.0")
            return 0.0

        # Sanity check: rate outside [-50%, +500%] is likely noise
        if rate < -0.5 or rate > 5.0:
            return 0.0
        return round(rate * 100.0, 2)

    def compute_max_drawdown(self, series: pd.Series) -> float:
        peak = series.cummax()
        dd = (series - peak) / peak * 100
        return round(abs(dd.min()), 2)

    def analyze(self, product_code: str, force_refresh: bool = False) -> PortfolioSummary:
        txns = self.load_transactions(product_code)
        if not txns:
            raise ValueError(f"No transactions found for {product_code}")

        nav = self.fetch_nav(product_code, force_refresh=force_refresh)
        daily = self.compute_daily_value(txns, nav)
        holdings = self.compute_holdings(daily, product_code)

        total_invested = sum(t.amount for t in txns if t.type == "buy")
        total_withdrawn = sum(t.amount for t in txns if t.type in ("sell", "dividend"))
        dividend_received = sum(t.amount for t in txns if t.type == "dividend")
        current_val = daily["market_value"].iloc[-1]
        total_pnl = current_val + total_withdrawn - total_invested
        total_pnl_pct = (
            (total_pnl / abs(total_invested)) * 100 if total_invested > 0 else 0.0
        )

        held = daily[daily["shares_held"] > 0]
        max_dd = self.compute_max_drawdown(held["nav"]) if len(held) > 0 else 0.0
        irr = self.compute_xirr(
            txns, float(current_val), daily["date"].iloc[-1]  # noqa: FBT003
        )

        buys = sum(1 for t in txns if t.type == "buy")
        sells = sum(1 for t in txns if t.type == "sell")

        return PortfolioSummary(
            product=product_code,
            holdings=holdings,
            transactions=txns,
            daily_value=daily,
            nav_history=nav,
            total_invested=round(total_invested, 2),
            total_withdrawn=round(total_withdrawn, 2),
            net_cash_flow=round(total_withdrawn - total_invested, 2),
            current_value=round(float(current_val), 2),
            total_pnl=round(total_pnl, 2),
            total_pnl_pct=round(total_pnl_pct, 2),
            max_drawdown_pct=max_dd,
            irr_annual_pct=irr,
            total_buys=buys,
            total_sells=sells,
            start_date=daily["date"].iloc[0].strftime("%Y-%m-%d"),
            end_date=daily["date"].iloc[-1].strftime("%Y-%m-%d"),
        )

    # ── Charts ─────────────────────────────────────────────────────────

    def portfolio_fig(self, summary: PortfolioSummary) -> go.Figure:
        daily = summary.daily_value
        txns = summary.transactions
        nav = summary.nav_history

        # ── Match buys/sells to NAV for markers ──
        # Build a lookup: for each trade date, find the actual NAV on that date
        nav_lookup = nav.set_index("date")["nav"].to_dict()

        buys = [t for t in txns if t.type == "buy"]
        sells = [t for t in txns if t.type == "sell"]

        buy_dates = [t.date for t in buys]
        buy_navs = [nav_lookup.get(t.date, None) for t in buys]
        buy_texts = [
            f"买入 {t.date.strftime('%Y-%m-%d')}<br>"
            f"金额: ¥{t.amount:,.2f}<br>"
            f"净值: {t.price:.4f}<br>"
            f"份额: {t.shares:.2f}<br>"
            + (f"手续费: ¥{t.fee:.2f}" if t.fee > 0 else "手续费: 0")
            for t in buys
        ]

        sell_dates = [t.date for t in sells]
        sell_navs = [nav_lookup.get(t.date, None) for t in sells]
        # Compute realized P&L per sell using FIFO cost matching
        sell_pnls = self._match_trade_pnl(buys, sells)
        sell_texts = [
            f"卖出 {t.date.strftime('%Y-%m-%d')}<br>"
            f"到账: ¥{t.amount:,.2f}<br>"
            f"净值: {t.price:.4f}<br>"
            f"份额: {t.shares:.2f}<br>"
            f"手续费: ¥{t.fee:.2f}<br>"
            f"<b>已实现盈亏: {_pnl_str(sell_pnls[i])}</b>"
            for i, t in enumerate(sells)
        ]

        fig = make_subplots(
            rows=3, cols=1, shared_xaxes=True,
            vertical_spacing=0.04,
            row_heights=[0.35, 0.40, 0.25],
            subplot_titles=("Portfolio Value", "NAV & Trade Markers", "Drawdown"),
        )

        fig.add_trace(go.Scatter(
            x=daily["date"], y=daily["market_value"],
            mode="lines", name="Market Value",
            line=dict(color="steelblue", width=1.5),
            fill="tozeroy", fillcolor="rgba(70,130,180,0.1)",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=daily["date"], y=daily["total_cost"],
            mode="lines", name="Cost Basis",
            line=dict(color="orange", width=1, dash="dash"),
        ), row=1, col=1)

        # NAV line
        fig.add_trace(go.Scatter(
            x=nav["date"], y=nav["nav"],
            mode="lines", name="NAV",
            line=dict(color="gold", width=1.5),
        ), row=2, col=1)

        # Buy markers — green triangle-up
        if buys:
            fig.add_trace(go.Scatter(
                x=buy_dates, y=buy_navs,
                mode="markers", name="Buy",
                marker=dict(symbol="triangle-up", size=12, color="green",
                            line=dict(width=1, color="darkgreen")),
                text=buy_texts, hoverinfo="text",
            ), row=2, col=1)

        # Sell markers — red triangle-down
        if sells:
            fig.add_trace(go.Scatter(
                x=sell_dates, y=sell_navs,
                mode="markers", name="Sell",
                marker=dict(symbol="triangle-down", size=12, color="red",
                            line=dict(width=1, color="darkred")),
                text=sell_texts, hoverinfo="text",
            ), row=2, col=1)

        if summary.holdings:
            avg_cost = summary.holdings[0].avg_cost
            if avg_cost > 0:
                fig.add_hline(
                    y=avg_cost, line_dash="dash", line_color="red",
                    annotation_text=f"Avg Cost {avg_cost:.4f}",
                    row=2, col=1,
                )

        nav_held = daily[daily["shares_held"] > 0]
        peak = nav_held["nav"].cummax()
        dd = ((nav_held["nav"] - peak) / peak * 100).fillna(0)
        fig.add_trace(go.Scatter(
            x=nav_held["date"], y=dd,
            mode="lines", name="Drawdown %",
            line=dict(color="firebrick", width=1),
            fill="tozeroy", fillcolor="rgba(178,34,34,0.15)",
        ), row=3, col=1)

        # ── Floating P&L summary annotation ──
        total_realized = sum(sell_pnls) if sell_pnls else 0.0
        unrealized = summary.total_pnl - total_realized
        ann_text = (
            f"已实现: {_pnl_str(total_realized)}<br>"
            f"浮动: {_pnl_str(unrealized)}<br>"
            f"总盈亏: {_pnl_str(summary.total_pnl)}"
        )
        fig.add_annotation(
            xref="paper", yref="paper", x=0.02, y=0.98,
            text=ann_text, showarrow=False,
            font=dict(size=12, color="#333"),
            align="left",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#ccc", borderwidth=1, borderpad=8,
        )

        fig.update_layout(
            title=f"Portfolio Analysis - {summary.product}",
            hovermode="x unified",
            template="plotly_white",
            height=1000,
        )
        fig.update_yaxes(title_text="Value (CNY)", row=1, col=1)
        fig.update_yaxes(title_text="NAV", row=2, col=1)
        fig.update_yaxes(title_text="DD %", row=3, col=1)

        return fig

    @staticmethod
    def _match_trade_pnl(buys: list[Transaction], sells: list[Transaction]) -> list[float]:
        """FIFO match sells against buys, returning realized P&L per sell."""
        if not sells:
            return []
        # Build buy queue: (date, shares, price_per_share, fee)
        from collections import deque
        q = deque()
        for b in buys:
            q.append((b.shares, b.price, b.fee, b.amount))
        pnls = []
        for s in sells:
            remaining = s.shares
            cost_basis = 0.0
            while remaining > 0 and q:
                b_shares, b_price, b_fee, b_amount = q[0]
                matched = min(remaining, b_shares)
                # Proportionally allocate cost
                ratio = matched / b_shares if b_shares > 0 else 0
                cost_basis += ratio * (b_amount - b_fee)
                remaining -= matched
                if matched >= b_shares:
                    q.popleft()
                else:
                    q[0] = (b_shares - matched, b_price, b_fee * (1 - ratio), b_amount * (1 - ratio))
            realized = s.amount - cost_basis
            pnls.append(round(realized, 2))
        return pnls

    # ── Signals ────────────────────────────────────────────────────────

    def get_signals(self, product_code: str) -> str:
        """Run strategies on NAV data and return a human-readable signal summary."""
        from Quantfolio.strategies.examples import (
            BollingerBreakout,
            LongTermBB,
            LongTermMA,
            LongTermRSI,
            MovingAverageCrossover,
            RSIStrategy,
        )

        nav = self.fetch_nav(product_code)

        data = nav.rename(columns={"nav": "close"})
        data["open"] = data["close"]
        data["high"] = data["close"]
        data["low"] = data["close"]

        strategies = [
            MovingAverageCrossover(self.cfg.sma_short, self.cfg.sma_long, self.cfg),
            RSIStrategy(self.cfg.rsi_period, self.cfg.rsi_oversold, self.cfg.rsi_overbought, self.cfg),
            BollingerBreakout(self.cfg.bollinger_period, self.cfg.bollinger_std, self.cfg),
            LongTermMA(self.cfg.lt_sma_short, self.cfg.lt_sma_long, self.cfg),
            LongTermRSI(self.cfg.lt_rsi_period, self.cfg.lt_rsi_oversold, self.cfg.lt_rsi_overbought, self.cfg),
            LongTermBB(self.cfg.lt_bollinger_period, self.cfg.lt_bollinger_std, self.cfg),
        ]

        lines = []
        for strat in strategies:
            df = strat.init(data)
            context = {"position": 0, "entry_price": 0}
            latest_sig = 0

            for i in range(len(df)):
                row = df.iloc[i]
                sig = strat.next(i, row, context)
                if i == len(df) - 1:
                    latest_sig = sig
                if sig == 1 and context["position"] == 0:
                    context["position"] = 1
                    context["entry_price"] = row["close"]
                elif sig == -1 and context["position"] == 1:
                    context["position"] = 0
                    context["entry_price"] = 0

            latest = df.iloc[-1]
            lines.append(self._format_signal(strat, latest, context, latest_sig))

        return "\n".join(lines)

    @staticmethod
    def _format_signal(strat, latest, context, latest_sig):
        name = strat.name
        close = latest["close"]

        if latest_sig == 1:
            tag = "[买入]"
        elif latest_sig == -1:
            tag = "[卖出]"
        elif context["position"] == 1:
            tag = "[持有]"
        else:
            tag = "[观望]"

        if name in ("MovingAverageCrossover", "LongTermMA"):
            short_k = strat.short_window
            long_k = strat.long_window
            sma_s = latest.get(f"sma_{short_k}")
            sma_l = latest.get(f"sma_{long_k}")
            if pd.notna(sma_s) and pd.notna(sma_l):
                relation = "多头" if sma_s > sma_l else "空头"
                hint = f"SMA{short_k}={sma_s:.4f} SMA{long_k}={sma_l:.4f} {relation}"
            else:
                hint = "数据不足"

        elif name in ("RSIStrategy", "LongTermRSI"):
            rsi = latest.get(f"rsi_{strat.period}")
            if pd.notna(rsi):
                if rsi < strat.oversold:
                    state = "超卖"
                elif rsi > strat.overbought:
                    state = "超买"
                else:
                    state = "中性"
                hint = f"RSI={rsi:.1f} {state} (超卖<{strat.oversold:.0f} 超买>{strat.overbought:.0f})"
            else:
                hint = "数据不足"

        elif name in ("BollingerBreakout", "LongTermBB"):
            upper = latest.get("bb_upper")
            middle = latest.get("bb_middle")
            lower = latest.get("bb_lower")
            if pd.notna(upper) and pd.notna(middle) and pd.notna(lower):
                if close > upper:
                    zone = "突破上轨"
                elif close < lower:
                    zone = "跌破下轨"
                elif close > middle:
                    zone = "中轨上方"
                else:
                    zone = "中轨下方"
                hint = f"价格{close:.4f} 上{upper:.4f} 中{middle:.4f} 下{lower:.4f} {zone}"
            else:
                hint = "数据不足"

        else:
            hint = ""

        return f"  {tag} {name}: {hint}"

    # ── Report ─────────────────────────────────────────────────────────

    def generate_report(self, product_code: str, save_html: bool = True, force_refresh: bool = False) -> str:
        summary = self.analyze(product_code, force_refresh=force_refresh)
        text = summary.summary()
        print(text)

        try:
            signals = self.get_signals(product_code)
            signal_header = f"\n  [策略信号 — {summary.end_date}]"
            print(signal_header)
            print(signals)
        except Exception:
            logger.exception("Failed to generate signals")

        if save_html:
            fig = self.portfolio_fig(summary)
            fig_path = self.portfolio_dir / f"{product_code}_report.html"
            fig.write_html(str(fig_path))
            logger.info("Report saved to %s", fig_path)
            print(f"\n交互式图表已保存至 {fig_path}")

        return text
