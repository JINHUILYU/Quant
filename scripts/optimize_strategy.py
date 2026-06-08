#!/usr/bin/env python3
"""Grid-search optimal strategy parameters per product.

Usage
-----
    # 搜索所有持仓产品的 optimal strategy
    python scripts/optimize_strategy.py

    # 指定产品
    python scripts/optimize_strategy.py --product 002611

    # 指定优化目标
    python scripts/optimize_strategy.py --objective sharpe  # default: total_return
    python scripts/optimize_strategy.py --objective calmar   # return / max_dd
    python scripts/optimize_strategy.py --objective win_rate

    # 看所有目标的对比
    python scripts/optimize_strategy.py --all-objectives
"""
from __future__ import annotations

import argparse
import itertools
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
import numpy as np

from Quantfolio.config import QuantfolioConfig
from Quantfolio.backtest.engine import BacktestEngine
from Quantfolio.strategies.base import Strategy
from Quantfolio.strategies.examples import (
    MovingAverageCrossover,
    RSIStrategy,
    BollingerBreakout,
    LongTermMA,
    LongTermRSI,
    LongTermBB,
)
from Quantfolio.data.store import LocalDataStore
from Quantfolio.portfolio.tracker import PortfolioTracker


# ═══════════════════════════════════════════════════════════════════════════
# Parameter grids
# ═══════════════════════════════════════════════════════════════════════════

# (strategy_class, param_name, values)
# Each entry generates one or more strategy instances

STRATEGY_GRIDS: list[tuple[type[Strategy], dict[str, list]]] = [
    (MovingAverageCrossover, {
        "short_window": [5, 10, 20, 30],
        "long_window":  [30, 50, 100, 150, 200],
    }),
    (RSIStrategy, {
        "period":      [7, 14, 21],
        "oversold":    [20, 25, 30],
        "overbought":  [70, 75, 80],
    }),
    (BollingerBreakout, {
        "period": [10, 20, 30, 50],
        "std":    [1.5, 2.0, 2.5, 3.0],
    }),
    (LongTermMA, {
        "short_window": [20, 50, 100],
        "long_window":  [100, 150, 200, 250],
    }),
    (LongTermRSI, {
        "period":      [14, 21, 30],
        "oversold":    [15, 20, 25],
        "overbought":  [75, 80, 85, 90],
    }),
    (LongTermBB, {
        "period": [30, 50, 100],
        "std":    [2.0, 2.5, 3.0, 3.5],
    }),
]


# Products to analyze (equity / gold / commodity — skip pure bond)
ANALYSIS_PRODUCTS: list[tuple[str, str]] = [
    ("002611", "博时黄金ETF联接C"),
    ("000217", "华安黄金ETF联接C"),
    ("000218", "国泰黄金ETF联接A"),
    ("009505", "富国上海金ETF联接C"),
    ("001302", "前海开源金银珠宝混合A"),
    ("161226", "国投瑞银白银期货LOF"),
    ("519674", "银河创新成长混合A"),
    ("470007", "汇添富上证综合指数A"),
    ("006220", "工银上证50ETF联接A"),
    ("110020", "易方达沪深300ETF联接A"),
    ("010786", "博时创业板指数C"),
    ("016452", "南方纳斯达克100 QDII A"),
    ("016453", "南方纳斯达克100 QDII C"),
    ("270042", "广发纳斯达克100 QDII"),
]

# Au99.99 gold spot (always included)
GOLD_SPOT = ("Au99.99", "Au99.99 黄金现货")


# ═══════════════════════════════════════════════════════════════════════════
# Result type
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class OptimizationResult:
    product: str
    product_name: str
    strategy_name: str
    params: dict
    total_return: float = 0.0
    cagr: float = 0.0
    max_dd: float = 0.0
    sharpe: float = 0.0
    calmar: float = 0.0
    win_rate: float = 0.0
    n_trades: int = 0
    profit_factor: float = 0.0

    @property
    def param_str(self) -> str:
        parts = [f"{k}={v}" for k, v in self.params.items()]
        return ", ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# Core optimization
# ═══════════════════════════════════════════════════════════════════════════

def _compute_sharpe(equity_curve: pd.Series, risk_free: float = 0.02) -> float:
    """Annualized Sharpe ratio from daily equity curve."""
    returns = equity_curve.pct_change().dropna()
    if len(returns) < 2:
        return 0.0
    # Filter out flat periods (strategy never entered)
    nonzero = returns[returns.abs() > 1e-10]
    if len(nonzero) < 2:
        return 0.0
    excess = nonzero - risk_free / 252
    std = excess.std()
    if std < 1e-10:
        return 0.0
    return float(excess.mean() / std * np.sqrt(252))


def _compute_profit_factor(trades) -> float:
    """Gross profit / gross loss from trade list."""
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    return gross_profit / gross_loss if gross_loss > 0 else float("inf")


def optimize_product(
    product_code: str,
    product_name: str,
    data: pd.DataFrame,
    config: QuantfolioConfig,
    objective: str = "total_return",
    max_combos: int = 2000,
) -> list[OptimizationResult]:
    """Grid-search best (strategy, params) for one product.

    *objective* may be "total_return", "sharpe", "calmar", "win_rate", "profit_factor".
    """
    engine = BacktestEngine(config)
    results: list[OptimizationResult] = []

    total_combos = sum(
        len(list(itertools.product(*g[1].values()))) for g in STRATEGY_GRIDS
    )

    for strat_cls, param_grid in STRATEGY_GRIDS:
        keys = list(param_grid.keys())
        values = list(param_grid.values())

        for combo in itertools.product(*values):
            params = dict(zip(keys, combo))

            # Constraint: short_window < long_window
            if "short_window" in params and "long_window" in params:
                if params["short_window"] >= params["long_window"]:
                    continue

            # Constraint: oversold < overbought
            if "oversold" in params and "overbought" in params:
                if params["oversold"] >= params["overbought"]:
                    continue

            try:
                strategy = strat_cls(**params, config=config)
            except TypeError:
                continue

            result = engine.run(strategy, data)
            eq = result["equity_curve"]["equity"].dropna()
            if len(eq) < 2:
                continue

            trades = result["trades"]
            initial = config.initial_capital
            final = float(eq.iloc[-1])
            total_ret = (final / initial - 1) * 100

            days = (data["date"].iloc[-1] - data["date"].iloc[0]).days
            yrs = max(days / 365.25, 0.01)
            cagr = ((final / initial) ** (1 / yrs) - 1) * 100 if final > 0 else -100

            peak = eq.cummax()
            dd = (eq - peak) / peak * 100
            max_dd_val = abs(dd.min())

            sharpe = _compute_sharpe(eq)
            calmar = cagr / max_dd_val if max_dd_val > 0 else 0
            n = len(trades)
            win_rate = (sum(1 for t in trades if t.pnl > 0) / n * 100) if n > 0 else 0
            pf = _compute_profit_factor(trades) if n > 0 else 0

            results.append(OptimizationResult(
                product=product_code,
                product_name=product_name,
                strategy_name=strategy.name,
                params=params,
                total_return=round(total_ret, 2),
                cagr=round(cagr, 2),
                max_dd=round(max_dd_val, 2),
                sharpe=round(sharpe, 2),
                calmar=round(calmar, 2),
                win_rate=round(win_rate, 1),
                n_trades=n,
                profit_factor=round(pf, 2) if pf != float("inf") else 999,
            ))

    # Sort by objective
    objective_key = {
        "total_return": "total_return",
        "sharpe": "sharpe",
        "calmar": "calmar",
        "win_rate": "win_rate",
        "profit_factor": "profit_factor",
    }.get(objective, "total_return")

    results.sort(key=lambda r: getattr(r, objective_key), reverse=True)
    return results


# ═══════════════════════════════════════════════════════════════════════════
# Display
# ═══════════════════════════════════════════════════════════════════════════

import re
import unicodedata

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def _dw(s: str) -> int:
    """Display width: CJK=2, ASCII=1. Strips ANSI codes first."""
    clean = re.sub(r"\033\[[0-9;]*m", "", s)
    w = 0
    for ch in clean:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def _pad(s: str, width: int, align: str = "<") -> str:
    """Pad *s* to *display width* (accounts for ANSI codes)."""
    d = _dw(s)
    pad_width = max(0, width - d)
    if align == ">":
        return " " * pad_width + s
    return s + " " * pad_width


def _color_ret(v: float | None, width: int = 7) -> str:
    """Colored return string, padded to *width* display chars."""
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return _pad(f"{DIM}N/A{RESET}", width)
    if v > 0:
        s = f"{GREEN}{v:+.1f}%{RESET}"
    elif v < 0:
        s = f"{RED}{v:.1f}%{RESET}"
    else:
        s = f"{DIM} 0.0%{RESET}"
    return _pad(s, width)


def _num_str(v: float | None, fmt: str = ".2f", width: int = 7) -> str:
    """Formatted number, grey N/A if None/NaN/Inf."""
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return _pad(f"{DIM}N/A{RESET}", width)
    s = f"{v:{fmt}}"
    return _pad(s, width)


def show_best_per_product(
    all_results: dict[str, list[OptimizationResult]],
    top_n: int = 3,
    objective: str = "total_return",
) -> None:
    """Print best strategy per product."""
    obj_labels = {
        "total_return": "总收益",
        "sharpe": "Sharpe",
        "calmar": "Calmar",
        "win_rate": "胜率",
        "profit_factor": "盈亏比",
    }
    obj_label = obj_labels.get(objective, objective)

    print(f"\n  {BOLD}🏆 各产品最优策略（按{CYAN}{obj_label}{RESET}{BOLD}排序）{RESET}")
    print()
    # Header with display-width-aware padding
    header = (
        f"  {_pad('产品', 22)} {_pad('最优策略', 22)} {_pad('参数', 34)} "
        f"{_pad('总收益', 7, '>')} {_pad('年化', 7, '>')} "
        f"{_pad('回撤', 6, '>')} {_pad('Sharpe', 6, '>')} "
        f"{_pad('胜率', 6, '>')} {_pad('交易', 4, '>')}"
    )
    print(header)
    print("  " + "─" * 122)

    for code, results in all_results.items():
        if not results:
            continue
        best = results[0]
        name = best.product_name
        strat = best.strategy_name
        params = best.param_str
        if len(params) > 33:
            params = params[:30] + "..."

        n_trades = best.n_trades
        trades_str = _pad(str(n_trades), 4, ">") if n_trades > 0 else _pad(f"{DIM}—{RESET}", 4, ">")

        print(
            f"  {_pad(name, 22)} {_pad(CYAN + strat + RESET, 22)} {_pad(params, 34)} "
            f"{_color_ret(best.total_return)} {_color_ret(best.cagr)} "
            f"{_num_str(best.max_dd, '.1f', 6)} {_num_str(best.sharpe, '.2f', 6)} "
            f"{_color_ret(best.win_rate, 6)} {trades_str}"
        )

    print()


def show_full_ranking(
    results: list[OptimizationResult],
    product_name: str,
    top_n: int = 20,
    objective: str = "total_return",
) -> None:
    """Show top-N strategy combinations for a single product."""
    obj_labels = {
        "total_return": "总收益",
        "sharpe": "Sharpe",
        "calmar": "Calmar",
        "win_rate": "胜率",
        "profit_factor": "盈亏比",
    }
    obj_label = obj_labels.get(objective, objective)

    # Deduplicate: show best per strategy type
    seen_strats: set[str] = set()
    deduped: list[OptimizationResult] = []
    for r in results:
        if r.strategy_name not in seen_strats:
            deduped.append(r)
            seen_strats.add(r.strategy_name)

    print(f"\n  {BOLD}📋 {product_name} — 各策略最优参数（按{CYAN}{obj_label}{RESET}{BOLD}）{RESET}")
    print()
    header = (
        f"  {_pad('策略', 24)} {_pad('最优参数', 40)} "
        f"{_pad('总收益', 7, '>')} {_pad('年化', 7, '>')} "
        f"{_pad('回撤', 6, '>')} {_pad('Sharpe', 6, '>')} "
        f"{_pad('Calmar', 6, '>')} {_pad('胜率', 6, '>')} {_pad('交易', 4, '>')}"
    )
    print(header)
    print("  " + "─" * 120)

    for r in deduped[:top_n]:
        params = r.param_str
        if len(params) > 39:
            params = params[:36] + "..."
        n_trades = r.n_trades
        trades_str = _pad(str(n_trades), 4, ">") if n_trades > 0 else _pad(f"{DIM}—{RESET}", 4, ">")

        print(
            f"  {_pad(CYAN + r.strategy_name + RESET, 24)} {_pad(params, 40)} "
            f"{_color_ret(r.total_return)} {_color_ret(r.cagr)} "
            f"{_num_str(r.max_dd, '.1f', 6)} {_num_str(r.sharpe, '.2f', 6)} "
            f"{_num_str(r.calmar, '.2f', 6)} {_color_ret(r.win_rate, 6)} {trades_str}"
        )

    # Buy & hold benchmark
    bh = next((r for r in results if r.strategy_name == "BuyAndHold"), None)
    if bh:
        print(f"  {'─' * 120}")
        print(
            f"  {DIM}📊 买入持有基准{RESET}     {'':40} "
            f"{_pad(f'{DIM}{bh.total_return:+.1f}%{RESET}', 7)} "
            f"{_pad(f'{DIM}{bh.cagr:+.1f}%{RESET}', 7)}"
        )
    print()


def show_all_objectives(
    all_results: dict[str, list[OptimizationResult]],
) -> None:
    """Show best strategy per product for each objective."""
    objectives = [
        ("total_return", "总收益"),
        ("sharpe", "Sharpe"),
        ("calmar", "Calmar"),
    ]

    print(f"\n  {BOLD}🎯 多目标对比 — 各产品在不同目标下的最优策略{RESET}")
    print()
    # Header
    parts = [f"  {_pad('产品', 22)}"]
    for _, label in objectives:
        parts.append(f"{_pad('策略', 20)} {_pad(label, 7, '>')}")
    print(" ".join(parts))
    print("  " + "─" * 120)

    for code, results in all_results.items():
        if not results:
            continue
        name = results[0].product_name
        row_parts = [f"  {_pad(name, 22)}"]
        for obj_key, _ in objectives:
            sorted_results = sorted(results, key=lambda r: getattr(r, obj_key), reverse=True)
            best = sorted_results[0]
            strat_short = _pad(CYAN + best.strategy_name[:18] + RESET, 20)
            ret = _color_ret(best.total_return)
            row_parts.append(f"{strat_short} {ret}")
        print(" ".join(row_parts))

    print()


# ═══════════════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════════════

def load_gold_data() -> pd.DataFrame:
    """Load Au99.99 spot data as OHLC DataFrame."""
    store = LocalDataStore()
    df = store.load("Au99.99")
    # Already has open/high/low/close columns
    return df


def load_fund_data(code: str) -> pd.DataFrame | None:
    """Load fund NAV as pseudo-OHLC DataFrame."""
    tracker = PortfolioTracker()
    try:
        nav = tracker.fetch_nav(code)
    except Exception:
        return None
    nav = nav.rename(columns={"nav": "close"})
    nav["open"] = nav["close"]
    nav["high"] = nav["close"]
    nav["low"] = nav["close"]
    return nav


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="网格搜索最优策略参数")
    parser.add_argument("--product", help="只分析指定产品代码")
    parser.add_argument("--objective", default="total_return",
                       choices=["total_return", "sharpe", "calmar", "win_rate", "profit_factor"],
                       help="优化目标 (default: total_return)")
    parser.add_argument("--capital", type=float, default=10000, help="起始资金 (default: 10000)")
    parser.add_argument("--top", type=int, default=3, help="每产品显示前N个策略 (default: 3)")
    parser.add_argument("--all-objectives", action="store_true", help="显示所有优化目标的对比")
    parser.add_argument("--detail", help="展开显示指定产品的完整排名")
    parser.add_argument("--gold-only", action="store_true", help="只分析黄金现货")
    parser.add_argument("--funds-only", action="store_true", help="只分析持仓基金")
    args = parser.parse_args()

    cfg = QuantfolioConfig()
    cfg.initial_capital = args.capital

    use_gold = not args.funds_only
    use_funds = not args.gold_only

    all_results: dict[str, list[OptimizationResult]] = {}

    # ── Au99.99 gold spot ──
    if use_gold and (args.product is None or args.product == "Au99.99"):
        code, name = GOLD_SPOT
        df = load_gold_data()
        if args.product:
            start_date = str(df["date"].min())[:10]
        else:
            start_date = "2023-01-01"
        df = df[df["date"] >= start_date].copy().reset_index(drop=True)

        if len(df) > 0:
            # Buy & hold benchmark
            start_price = float(df.iloc[0]["close"])
            end_price = float(df.iloc[-1]["close"])
            bh_ret = (end_price / start_price - 1) * 100
            days = (df["date"].iloc[-1] - df["date"].iloc[0]).days
            yrs = max(days / 365.25, 0.01)
            bh_cagr = ((1 + bh_ret / 100) ** (1 / yrs) - 1) * 100

            print(f"\n  🔍 搜索 {name} ({df.iloc[0]['date'].strftime('%Y-%m-%d')} → {df.iloc[-1]['date'].strftime('%Y-%m-%d')})")
            print(f"     买入持有: {bh_ret:+.1f}%  年化: {bh_cagr:+.1f}%  数据点: {len(df)}")

            results = optimize_product(code, name, df, cfg, args.objective)
            # Add buy-hold pseudo-result
            results.append(OptimizationResult(
                product=code, product_name=name,
                strategy_name="BuyAndHold", params={},
                total_return=round(bh_ret, 2), cagr=round(bh_cagr, 2),
            ))
            all_results[code] = results

    # ── Portfolio funds ──
    if use_funds and args.product != "Au99.99":
        products_to_analyze = ANALYSIS_PRODUCTS
        if args.product:
            products_to_analyze = [(args.product, "") for p in ANALYSIS_PRODUCTS if p[0] == args.product]

        for code, name in products_to_analyze:
            if not name:
                # Try to get name from portfolio data
                try:
                    txn_df = pd.read_csv(f"data/portfolio/{code}.csv", dtype={"product": str})
                    name = str(txn_df["notes"].iloc[0]) if "notes" in txn_df.columns else code
                except Exception:
                    name = code

            nav = load_fund_data(code)
            if nav is None or len(nav) < 50:
                continue

            # Use first transaction date as start
            try:
                txn_df = pd.read_csv(f"data/portfolio/{code}.csv", dtype={"product": str})
                first_txn = str(txn_df["date"].min())[:10]
            except Exception:
                first_txn = str(nav["date"].min())[:10]

            data = nav[nav["date"] >= first_txn].copy().reset_index(drop=True)
            if len(data) < 50:
                continue

            start_price = float(data.iloc[0]["close"])
            end_price = float(data.iloc[-1]["close"])
            bh_ret = (end_price / start_price - 1) * 100

            print(f"\n  🔍 搜索 {name} ({first_txn} → {str(data['date'].iloc[-1])[:10]})")
            print(f"     买入持有: {bh_ret:+.1f}%  数据点: {len(data)}")

            results = optimize_product(code, name, data, cfg, args.objective)
            results.append(OptimizationResult(
                product=code, product_name=name,
                strategy_name="BuyAndHold", params={},
                total_return=round(bh_ret, 2),
            ))
            all_results[code] = results

    # ── Display ──
    if args.detail:
        code = args.detail
        if code in all_results:
            show_full_ranking(all_results[code], all_results[code][0].product_name,
                            objective=args.objective)
        else:
            print(f"[ERROR] 产品 {code} 无数据")

    elif args.all_objectives:
        show_all_objectives(all_results)

    else:
        show_best_per_product(all_results, args.top, args.objective)

    print(f"  💡 使用 --detail <code> 查看单个产品的完整策略排名")
    print(f"     --all-objectives 查看多目标（收益/Sharpe/Calmar/胜率）对比")
    print(f"     --objective sharpe 切换到风险调整后收益排序")
    print()


if __name__ == "__main__":
    main()
