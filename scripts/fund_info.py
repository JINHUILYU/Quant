#!/usr/bin/env python3
"""Quick fund data queries — no more ad-hoc Python one-liners.

Usage:
    python scripts/fund_info.py nav 002611                  # 最近 20 天净值
    python scripts/fund_info.py nav 002611 --days 60        # 最近 60 天
    python scripts/fund_info.py nav 002611 --asc            # 升序排列
    python scripts/fund_info.py calendar 002611 2026-05-01 2026-05-28  # 区间交易日
    python scripts/fund_info.py stats 002611                # 近期统计
    python scripts/fund_info.py stats 002611 --days 90      # 90 天统计
    python scripts/fund_info.py lookup 002611               # 查基金名称
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from Quantfolio.portfolio.tracker import PortfolioTracker


# ── Display-width helpers (CJK = 2, ASCII = 1) ─────────────────────────

def _dw(s: str) -> int:
    """Display width: CJK characters count as 2."""
    import unicodedata
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def _pad(s: str, width: int, align: str = "<") -> str:
    """Pad *s* to *display width*."""
    d = _dw(s)
    pad = max(0, width - d)
    if align == ">":
        return " " * pad + s
    return s + " " * pad  # left-align default


def cmd_nav(args) -> None:
    """Show recent NAV history for a fund."""
    nav = _fetch(args.product)
    days = args.days
    recent = nav.tail(days)
    if not args.asc:
        recent = recent.iloc[::-1]

    DATE_W, NAV_W, CHG_W = 12, 10, 10
    sep_w = 2 + DATE_W + 1 + NAV_W + 2 + CHG_W

    prev = None
    print()
    print(f"  {_pad('日期', DATE_W)} {_pad('净值', NAV_W, '>')}  {_pad('涨跌', CHG_W, '>')}")
    print("  " + "─" * (sep_w - 2))
    for _, r in recent.iterrows():
        curr = r["nav"]
        if prev is not None:
            chg_str = f"{(curr - prev) / prev * 100:+.2f}%"
        else:
            chg_str = ""
        date_str = r["date"].strftime("%Y-%m-%d")
        print(f"  {_pad(date_str, DATE_W)} {_pad(f'{curr:.4f}', NAV_W, '>')}  {_pad(chg_str, CHG_W, '>')}")
        prev = curr
    print()


def cmd_calendar(args) -> None:
    """List trading days with NAV in a date range."""
    nav = _fetch(args.product)
    from_dt = pd.Timestamp(_parse_date(args.from_date))
    to_dt = pd.Timestamp(_parse_date(args.to_date))
    mask = (nav["date"] >= from_dt) & (nav["date"] <= to_dt)
    subset = nav[mask]

    if subset.empty:
        print(f"  区间内无交易数据")
        return

    DATE_W, WD_W, NAV_W = 12, 6, 10
    sep_w = 2 + DATE_W + 1 + WD_W + 1 + NAV_W
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    print()
    print(f"  {_pad('日期', DATE_W)} {_pad('周几', WD_W)} {_pad('净值', NAV_W, '>')}")
    print("  " + "─" * (sep_w - 2))
    for _, r in subset.iterrows():
        wd = weekdays[r["date"].dayofweek]
        date_str = r["date"].strftime("%Y-%m-%d")
        print(f"  {_pad(date_str, DATE_W)} {_pad(wd, WD_W)} {_pad(f'{r['nav']:.4f}', NAV_W, '>')}")
    print(f"\n  共 {len(subset)} 个交易日")
    print()


def cmd_stats(args) -> None:
    """Quick statistics for recent period."""
    nav = _fetch(args.product)
    days = args.days
    subset = nav.tail(days)
    prices = subset["nav"].values

    if len(prices) < 2:
        print("  数据不足")
        return

    latest = prices[-1]
    first = prices[0]
    peak = prices.max()
    trough = prices.min()
    sma5 = prices[-5:].mean() if len(prices) >= 5 else prices.mean()
    sma20 = prices[-20:].mean() if len(prices) >= 20 else prices.mean()

    # Simple RSI-14 approximation
    if len(prices) >= 15:
        deltas = pd.Series(prices).diff()
        gains = deltas.clip(lower=0).tail(14).mean()
        losses = (-deltas.clip(upper=0)).tail(14).mean()
        rs = gains / losses if losses > 0 else float("inf")
        rsi = 100 - 100 / (1 + rs)
    else:
        rsi = float("nan")

    period_chg = (latest - first) / first * 100
    drawdown = (peak - trough) / peak * 100

    print()
    print(f"  ── {args.product} {days}天统计 ──")
    print(f"  最新净值:  {latest:.4f}")
    print(f"  {days}日前:   {first:.4f}")
    print(f"  区间涨跌:  {period_chg:+.2f}%")
    print(f"  最高:      {peak:.4f}  日期: {subset['date'].iloc[prices.argmax()].strftime('%Y-%m-%d')}")
    print(f"  最低:      {trough:.4f}  日期: {subset['date'].iloc[prices.argmin()].strftime('%Y-%m-%d')}")
    print(f"  最大回撤:  {drawdown:.2f}%")
    print(f"  SMA5:      {sma5:.4f}")
    print(f"  SMA20:     {sma20:.4f}")
    print(f"  RSI14:     {rsi:.1f}" if not pd.isna(rsi) else "  RSI14:     数据不足")
    print(f"  价格 vs SMA20: {(latest/sma20-1)*100:+.2f}%")
    print(f"  价格 vs 区间高: {(latest/peak-1)*100:+.2f}% (从高点回撤)")
    print()


def cmd_lookup(args) -> None:
    """Show fund name from transaction notes, or fetch latest NAV to identify."""
    from Quantfolio.config import QuantfolioConfig

    cfg = QuantfolioConfig()
    csv_path = cfg.portfolio_dir_abs / f"{args.product}.csv"

    if csv_path.exists():
        df = pd.read_csv(csv_path, dtype={"product": str})
        notes = df["notes"].dropna()
        if not notes.empty:
            name = notes.iloc[0]
            print(f"  {args.product} = {name}")
            return

    # Fallback: try to show latest NAV date
    try:
        nav = _fetch(args.product)
        print(f"  {args.product}: 最新净值日 {nav['date'].iloc[-1].strftime('%Y-%m-%d')}, 净值 {nav['nav'].iloc[-1]:.4f}")
    except Exception:
        print(f"  {args.product}: 未找到本地记录，也无法获取净值")


def _fetch(product: str) -> pd.DataFrame:
    """Fetch NAV, sorted chronologically."""
    tracker = PortfolioTracker()
    nav = tracker.fetch_nav(product)
    return nav.sort_values("date").reset_index(drop=True)


def _parse_date(s: str) -> str:
    """Accept YYYY-MM-DD or MM-DD (current year assumed)."""
    if "-" not in s:
        raise ValueError(f"无效日期: {s}")
    parts = s.split("-")
    if len(parts[0]) == 2:
        s = f"{datetime.now().year}-{s}"
    return s


def main() -> None:
    parser = argparse.ArgumentParser(description="快速基金数据查询")
    sub = parser.add_subparsers(dest="command")

    p_nav = sub.add_parser("nav", help="查看近期净值走势")
    p_nav.add_argument("product", help="基金代码")
    p_nav.add_argument("--days", type=int, default=20, help="显示最近多少天（默认 20）")
    p_nav.add_argument("--asc", action="store_true", help="升序排列")

    p_cal = sub.add_parser("calendar", help="列出区间内交易日及净值")
    p_cal.add_argument("product", help="基金代码")
    p_cal.add_argument("from_date", help="起始日期 YYYY-MM-DD 或 MM-DD")
    p_cal.add_argument("to_date", help="结束日期 YYYY-MM-DD 或 MM-DD")

    p_stats = sub.add_parser("stats", help="近期统计摘要")
    p_stats.add_argument("product", help="基金代码")
    p_stats.add_argument("--days", type=int, default=60, help="统计区间天数（默认 60）")

    p_lookup = sub.add_parser("lookup", help="查询基金名称")
    p_lookup.add_argument("product", help="基金代码")

    args = parser.parse_args()

    if args.command == "nav":
        cmd_nav(args)
    elif args.command == "calendar":
        cmd_calendar(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "lookup":
        cmd_lookup(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
