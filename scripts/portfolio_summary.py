#!/usr/bin/env python3
"""Portfolio summary: P&L and return across all products.

Usage:
    python scripts/portfolio_summary.py
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from GoldQuant.config import GoldQuantConfig
from GoldQuant.portfolio.tracker import PortfolioTracker


def _display_width(s: str) -> int:
    """Return the display width of *s*, counting CJK chars as 2."""
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def _pad(s: str, width: int, align: str = "<") -> str:
    """Pad *s* to *display width*, handling CJK characters."""
    dw = _display_width(s)
    padding = max(0, width - dw)
    if align == "<":
        return s + " " * padding
    elif align == ">":
        return " " * padding + s
    else:
        left = padding // 2
        right = padding - left
        return " " * left + s + " " * right


def _truncate(s: str, display_width: int) -> str:
    """Truncate *s* so its display width does not exceed *display_width*."""
    w = 0
    result: list[str] = []
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > display_width:
            break
        result.append(ch)
        w += cw
    return "".join(result)


def main() -> None:
    cfg = GoldQuantConfig()
    tracker = PortfolioTracker(cfg)

    products: list[str] = sorted(
        p.stem for p in cfg.portfolio_dir_abs.glob("*.csv") if p.stem != "template"
    )

    if not products:
        print("没有找到任何产品交易记录。")
        return

    rows: list[dict] = []
    total_invested = 0.0
    total_withdrawn = 0.0
    total_market_val = 0.0
    total_realized = 0.0
    total_unrealized = 0.0

    for product in products:
        try:
            summary = tracker.analyze(product)
        except Exception as e:
            print(f"  [WARN] {product} 分析失败: {e}")
            continue

        invested = summary.total_invested
        withdrawn = summary.total_withdrawn
        market_val = summary.current_value
        total_pnl = summary.total_pnl
        total_pnl_pct = summary.total_pnl_pct
        unrealized = summary.holdings[0].unrealized_pnl if summary.holdings else 0.0
        realized = total_pnl - unrealized

        notes = ""
        if summary.transactions:
            notes = summary.transactions[0].notes

        rows.append({
            "code": product,
            "name": notes,
            "invested": invested,
            "withdrawn": withdrawn,
            "market_val": market_val,
            "realized": realized,
            "unrealized": unrealized,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
        })

        total_invested += invested
        total_withdrawn += withdrawn
        total_market_val += market_val
        total_realized += realized
        total_unrealized += unrealized

    # ── Output ────────────────────────────────────────────────────────────────

    CODE_W = 8
    NAME_W = 28
    NUM_W = 12
    PCT_W = 10

    # Display width: "  " + CODE_W + " " + NAME_W + " " + 6*NUM_W + 6*" " + PCT_W + "%"
    SEP_W = 2 + CODE_W + 1 + NAME_W + 1 + NUM_W * 6 + 6 + PCT_W + 1

    def _fmt_row(code: str, name: str, inv: float, wdr: float, mval: float,
                 real: float, unreal: float, pnl: float, pct: float) -> str:
        return (
            f"  {_pad(code, CODE_W)} {_pad(_truncate(name, NAME_W), NAME_W)} "
            f"{inv:{NUM_W},.2f} {wdr:{NUM_W},.2f} {mval:{NUM_W},.2f} "
            f"{real:{NUM_W},.2f} {unreal:{NUM_W},.2f} {pnl:{NUM_W},.2f} "
            f"{pct:{PCT_W}.2f}%"
        )

    def _fmt_header(code: str, name: str, inv: str, wdr: str, mval: str,
                    real: str, unreal: str, pnl: str, pct: str) -> str:
        return (
            f"  {_pad(code, CODE_W)} {_pad(name, NAME_W)} "
            f"{_pad(inv, NUM_W, '>')} {_pad(wdr, NUM_W, '>')} {_pad(mval, NUM_W, '>')} "
            f"{_pad(real, NUM_W, '>')} {_pad(unreal, NUM_W, '>')} {_pad(pnl, NUM_W, '>')} "
            f"{_pad(pct, PCT_W, '>')}"
        )

    sep = "─" * SEP_W

    print()
    print(sep)
    print(f"  📊 投资组合汇总")
    print(sep)
    print(_fmt_header("代码", "基金名称", "累计投入", "累计取出", "持仓市值",
                       "已实现盈亏", "浮动盈亏", "总盈亏", "收益率"))
    print("  " + "─" * (SEP_W - 2))

    for r in rows:
        print(_fmt_row(
            r["code"], r["name"], r["invested"], r["withdrawn"], r["market_val"],
            r["realized"], r["unrealized"], r["total_pnl"], r["total_pnl_pct"],
        ))

    print("  " + "─" * (SEP_W - 2))
    grand_total_pnl = total_market_val + total_withdrawn - total_invested
    grand_pnl_pct = (grand_total_pnl / total_invested * 100) if total_invested else 0
    print(_fmt_row(
        "合计", "", total_invested, total_withdrawn, total_market_val,
        total_realized, total_unrealized, grand_total_pnl, grand_pnl_pct,
    ))
    print(sep)
    print()


if __name__ == "__main__":
    main()
