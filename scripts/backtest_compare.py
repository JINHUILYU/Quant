#!/usr/bin/env python3
"""Strategy backtest + portfolio comparison tool.

Two modes
--------
gold       Backtest strategies on Au99.99 spot data.
portfolio  Backtest strategies on portfolio fund NAVs + compare with actual returns.

Usage
-----
    python scripts/backtest_compare.py gold [--capital 10000] [--from 2023-01-01]
    python scripts/backtest_compare.py portfolio [--capital 10000]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
import numpy as np

from Quantfolio.config import QuantfolioConfig
from Quantfolio.backtest.engine import BacktestEngine
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
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_strategies(cfg: QuantfolioConfig) -> list:
    """All available strategies with default parameters."""
    return [
        MovingAverageCrossover(cfg.sma_short, cfg.sma_long, cfg),
        RSIStrategy(cfg.rsi_period, cfg.rsi_oversold, cfg.rsi_overbought, cfg),
        BollingerBreakout(cfg.bollinger_period, cfg.bollinger_std, cfg),
        LongTermMA(cfg.lt_sma_short, cfg.lt_sma_long, cfg),
        LongTermRSI(cfg.lt_rsi_period, cfg.lt_rsi_oversold, cfg.lt_rsi_overbought, cfg),
        LongTermBB(cfg.lt_bollinger_period, cfg.lt_bollinger_std, cfg),
    ]


def _compute_metrics(equity_curve: pd.DataFrame, initial_capital: float) -> dict:
    """Compute summary metrics from equity curve."""
    eq = equity_curve["equity"].dropna()
    if len(eq) == 0:
        return {"final": initial_capital, "total_return": 0, "cagr": 0,
                "max_dd": 0, "trades": 0, "win_rate": 0}

    final = float(eq.iloc[-1])
    total_ret = (final / initial_capital - 1) * 100

    days = (eq.index[-1] - eq.index[0]) if hasattr(eq.index[-1], 'days') else len(eq)
    if hasattr(equity_curve["date"].iloc[0], 'strftime'):
        days = (equity_curve["date"].iloc[-1] - equity_curve["date"].iloc[0]).days
    yrs = max(days / 365.25, 0.01)
    cagr = ((final / initial_capital) ** (1 / yrs) - 1) * 100

    peak = eq.cummax()
    dd = (eq - peak) / peak * 100
    max_dd = abs(dd.min())

    return {
        "final": final,
        "total_return": round(total_ret, 1),
        "cagr": round(cagr, 1),
        "max_dd": round(max_dd, 1),
        "years": round(yrs, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Gold mode
# ═══════════════════════════════════════════════════════════════════════════

def run_gold(args) -> None:
    """Backtest all strategies on Au99.99 spot data."""
    store = LocalDataStore()
    df = store.load("Au99.99")

    start_date = getattr(args, 'from_date', '2023-01-01') or '2023-01-01'
    df = df[df["date"] >= start_date].copy().reset_index(drop=True)

    if len(df) == 0:
        print(f"[ERROR] Au99.99 数据在 {start_date} 之后为空")
        return

    cfg = QuantfolioConfig()
    cfg.initial_capital = args.capital

    start_price = float(df.iloc[0]["close"])
    end_price = float(df.iloc[-1]["close"])
    bh_ret = (end_price / start_price - 1) * 100
    years = (df.iloc[-1]["date"] - df.iloc[0]["date"]).days / 365.25
    bh_cagr = ((1 + bh_ret / 100) ** (1 / years) - 1) * 100

    print(f"\n  ╔{'═' * 60}╗")
    print(f"  ║  🥇 Au99.99 黄金现货 — 策略回测{' ' * 32}║")
    print(f"  ╚{'═' * 60}╝")
    print(f"  期间: {df.iloc[0]['date'].strftime('%Y-%m-%d')} → {df.iloc[-1]['date'].strftime('%Y-%m-%d')}")
    print(f"  交易日: {len(df)}  起始资金: ¥{args.capital:,}")
    print(f"  金价: ¥{start_price:.2f} → ¥{end_price:.2f}")
    print(f"  买入持有: {bh_ret:+.1f}%  年化: {bh_cagr:+.1f}%")
    print()

    engine = BacktestEngine(cfg)
    strategies = _make_strategies(cfg)

    rows: list[dict] = []
    for strat in strategies:
        result = engine.run(strat, df)
        m = _compute_metrics(result["equity_curve"], args.capital)
        m["name"] = strat.name
        m["trades"] = len(result["trades"])
        trades = result["trades"]
        if m["trades"] > 0:
            wins = sum(1 for t in trades if t.pnl > 0)
            m["win_rate"] = round(wins / m["trades"] * 100, 1)
        else:
            m["win_rate"] = 0
        rows.append(m)

    # Sort by total return
    rows.sort(key=lambda r: r["total_return"], reverse=True)

    print(f"  {'策略':<28} {'最终权益':>10} {'总收益':>8} {'年化':>7} {'交易':>5} {'胜率':>6} {'最大回撤':>7}")
    print("  " + "─" * 75)
    for r in rows:
        print(f"  {r['name']:<28} {r['final']:>10,.0f} {r['total_return']:>7.1f}% {r['cagr']:>6.1f}% {r['trades']:>5} {r['win_rate']:>5.1f}% {r['max_dd']:>6.1f}%")

    print(f"\n  {'基准 (买入持有)':<28} {args.capital * (1 + bh_ret/100):>10,.0f} {bh_ret:>7.1f}% {bh_cagr:>6.1f}%")
    print()


# ═══════════════════════════════════════════════════════════════════════════
# Portfolio mode
# ═══════════════════════════════════════════════════════════════════════════

# Products suitable for backtesting (equity / gold / commodity, not pure bond)
PORTFOLIO_PRODUCTS: list[tuple[str, str]] = [
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


def run_portfolio(args) -> None:
    """Backtest strategies on portfolio fund NAVs + compare with actual returns."""
    tracker = PortfolioTracker()
    cfg = QuantfolioConfig()
    cfg.initial_capital = args.capital
    engine = BacktestEngine(cfg)

    # ── Get actual returns from portfolio_summary ──
    actual_returns: dict[str, float] = {}
    try:
        import subprocess
        result = subprocess.run(
            ["uv", "run", "python3", "scripts/portfolio_summary.py"],
            capture_output=True, text=True, timeout=60,
        )
        for line in result.stdout.split("\n"):
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit() and len(parts[0]) == 6:
                try:
                    actual_returns[parts[0]] = float(parts[-1].rstrip("%"))
                except ValueError:
                    pass
    except Exception:
        print("[WARN] 无法获取 portfolio_summary，实际收益列将为空")

    print(f"\n  ╔{'═' * 80}╗")
    print(f"  ║  📊 策略回测 vs 买入持有 vs 实际持仓收益{' ' * 41}║")
    print(f"  ╚{'═' * 80}╝")
    print(f"  起始资金: ¥{args.capital:,}  |  策略: MA交叉 / 布林突破 / 长线布林")
    print()

    header = f"  {'产品':<24} {'起始':>8}  {'买入持有':>8}  {'MA交叉':>8}  {'布林':>8}  {'最佳策略':>8}  {'实际收益':>8}  {'α':>7}"
    print(header)
    print("  " + "─" * 95)

    for code, name in PORTFOLIO_PRODUCTS:
        try:
            nav = tracker.fetch_nav(code)
            nav = nav.rename(columns={"nav": "close"})
            nav["open"] = nav["close"]
            nav["high"] = nav["close"]
            nav["low"] = nav["close"]
        except Exception:
            print(f"  {name:<24} {'N/A':>8}  {'获取失败':>8}")
            continue

        # Use first transaction date as start
        txn_file = Path(f"data/portfolio/{code}.csv")
        if not txn_file.exists():
            continue
        txn_df = pd.read_csv(txn_file, dtype={"product": str})
        first_txn = str(txn_df["date"].min())[:10]

        data = nav[nav["date"] >= first_txn].copy().reset_index(drop=True)
        if len(data) < 30:
            continue

        start_price = float(data.iloc[0]["close"])
        end_price = float(data.iloc[-1]["close"])
        bh_ret = (end_price / start_price - 1) * 100

        # Run 3 key strategies
        strats = [
            MovingAverageCrossover(cfg.sma_short, cfg.sma_long, cfg),
            BollingerBreakout(cfg.bollinger_period, cfg.bollinger_std, cfg),
            LongTermBB(cfg.lt_bollinger_period, cfg.lt_bollinger_std, cfg),
        ]
        strat_results: dict[str, float] = {}
        for s in strats:
            r = engine.run(s, data)
            eq = r["equity_curve"]["equity"].dropna()
            if len(eq) > 0 and eq.iloc[-1] > 0:
                strat_results[s.name] = (eq.iloc[-1] / args.capital - 1) * 100

        ma_ret = strat_results.get("MovingAverageCrossover")
        bb_ret = strat_results.get("BollingerBreakout")
        best_ret = max(strat_results.values()) if strat_results else None
        actual = actual_returns.get(code)

        ma_s = f"{ma_ret:>7.1f}%" if ma_ret is not None else "     N/A"
        bb_s = f"{bb_ret:>7.1f}%" if bb_ret is not None else "     N/A"
        best_s = f"{best_ret:>7.1f}%" if best_ret is not None else "     N/A"
        actual_s = f"{actual:>7.1f}%" if actual is not None else "     N/A"

        alpha = (actual - bh_ret) if (actual is not None) else 0
        alpha_mark = "✅" if alpha > 0 else "➖"

        print(f"  {name:<24} {first_txn:>8}  {bh_ret:>7.1f}%  {ma_s}  {bb_s}  {best_s}  {actual_s}  {alpha_mark}{alpha:>+5.1f}%")

    print()
    print("  💡 α = 实际收益 − 买入持有。✅ = 择时/定投产生正超额  ➖ = 跑输基准")
    print("     跑输不一定不好——主动减仓锁利会降低收益但也降低了风险。")
    print()


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="策略回测 + 持仓对比",
    )
    sub = parser.add_subparsers(dest="mode")

    p_gold = sub.add_parser("gold", help="Au99.99 黄金现货策略回测")
    p_gold.add_argument("--capital", type=float, default=10000, help="起始资金 (default: 10000)")
    p_gold.add_argument("--from", dest="from_date", default="2023-01-01", help="起始日期 (default: 2023-01-01)")

    p_port = sub.add_parser("portfolio", help="持仓基金策略回测 + 实际收益对比")
    p_port.add_argument("--capital", type=float, default=10000, help="起始资金 (default: 10000)")

    args = parser.parse_args()

    if args.mode == "gold":
        run_gold(args)
    elif args.mode == "portfolio":
        run_portfolio(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
