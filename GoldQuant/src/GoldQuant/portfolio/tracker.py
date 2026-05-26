from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from GoldQuant.config import GoldQuantConfig
from GoldQuant.portfolio.models import Holding, PortfolioSummary, Transaction

logger = logging.getLogger(__name__)


class PortfolioTracker:
    """Portfolio analysis for Chinese fund transactions.

    Loads transaction CSVs from data/portfolio/, fetches NAV via akshare,
    computes holdings, P&L, drawdown, and XIRR.
    """

    def __init__(self, config: GoldQuantConfig | None = None):
        self.cfg = config or GoldQuantConfig()

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

        invalid = df[~df["type"].isin(["buy", "sell"])]
        if not invalid.empty:
            raise ValueError(
                f"Invalid type values at rows {invalid.index.tolist()}: "
                f"must be 'buy' or 'sell'"
            )

        transactions = []
        for _, row in df.iterrows():
            transactions.append(Transaction(
                date=row["date"],
                product=str(row["product"]),
                type=str(row["type"]),
                amount=float(row["amount"]),
                price=float(row["price"]),
                shares=float(row["shares"]),
                fee=float(row.get("fee", 0.0) or 0.0),
                notes=str(row.get("notes", "") or ""),
            ))
        return transactions

    # ── NAV fetching ───────────────────────────────────────────────────

    @staticmethod
    def fetch_nav(product_code: str) -> pd.DataFrame:
        import akshare as ak

        df = ak.fund_open_fund_info_em(symbol=product_code, indicator="单位净值走势")
        df = df.rename(columns={"净值日期": "date", "单位净值": "nav"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df[["date", "nav"]]

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

        if shares > 0 and cost > 0:
            avg_cost = cost / shares
            pnl = mkt_val - cost
            pnl_pct = (mkt_val / cost - 1) * 100
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
                return round(rate * 100.0, 2)

            if dnpv == 0.0:
                break

            rate -= npv / dnpv
            if rate < -0.999:
                rate = -0.999
            elif rate > 10.0:
                rate = 10.0

        logger.warning("XIRR did not converge; returning 0.0")
        return 0.0

    def compute_max_drawdown(self, series: pd.Series) -> float:
        peak = series.cummax()
        dd = (series - peak) / peak * 100
        return round(abs(dd.min()), 2)

    def analyze(self, product_code: str) -> PortfolioSummary:
        txns = self.load_transactions(product_code)
        if not txns:
            raise ValueError(f"No transactions found for {product_code}")

        nav = self.fetch_nav(product_code)
        daily = self.compute_daily_value(txns, nav)
        holdings = self.compute_holdings(daily, product_code)

        total_invested = sum(t.amount for t in txns if t.type == "buy")
        total_withdrawn = sum(t.amount for t in txns if t.type == "sell")
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

        fig = make_subplots(
            rows=3, cols=1, shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.4, 0.35, 0.25],
            subplot_titles=("Portfolio Value", "NAV & Average Cost", "Drawdown"),
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

        fig.add_trace(go.Scatter(
            x=summary.nav_history["date"], y=summary.nav_history["nav"],
            mode="lines", name="NAV",
            line=dict(color="gold", width=1.5),
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

        fig.update_layout(
            title=f"Portfolio Analysis - {summary.product}",
            hovermode="x unified",
            template="plotly_white",
            height=800,
        )
        fig.update_yaxes(title_text="Value (CNY)", row=1, col=1)
        fig.update_yaxes(title_text="NAV", row=2, col=1)
        fig.update_yaxes(title_text="DD %", row=3, col=1)

        return fig

    # ── Signals ────────────────────────────────────────────────────────

    def get_signals(self, product_code: str) -> str:
        """Run strategies on NAV data and return a human-readable signal summary."""
        from GoldQuant.strategies.examples import (
            BollingerBreakout,
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

        if name == "MovingAverageCrossover":
            short_k = strat.short_window
            long_k = strat.long_window
            sma_s = latest.get(f"sma_{short_k}")
            sma_l = latest.get(f"sma_{long_k}")
            if pd.notna(sma_s) and pd.notna(sma_l):
                relation = "多头" if sma_s > sma_l else "空头"
                hint = f"SMA{short_k}={sma_s:.4f} SMA{long_k}={sma_l:.4f} {relation}"
            else:
                hint = "数据不足"

        elif name == "RSIStrategy":
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

        elif name == "BollingerBreakout":
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

    def generate_report(self, product_code: str, save_html: bool = True) -> str:
        summary = self.analyze(product_code)
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
