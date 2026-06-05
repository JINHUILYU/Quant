#!/usr/bin/env python3
"""Show recent transactions across all funds.

Usage:
    python scripts/recent_txns.py [--days N] [--product CODE] [--type buy|sell|dividend]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from wcwidth import wcswidth

PORTFOLIO_DIR = Path(__file__).resolve().parent.parent / "data" / "portfolio"

# Column layout: (header, width, align)
# align: '<' left, '>' right
COLUMNS = [
    ("日期",    10, "<"),
    ("代码",     6, "<"),
    ("类型",     6, "<"),
    ("金额",     8, ">"),
    ("净值",     8, ">"),
    ("份额",     8, ">"),
    ("手续费",   6, ">"),
]


def display_width(s: str) -> int:
    """Return terminal display width of a string (CJK chars = 2)."""
    w = wcswidth(s)
    return w if w >= 0 else len(s)


def pad(s: str, width: int, align: str = "<") -> str:
    """Pad string to exact terminal display width, accounting for CJK."""
    dw = display_width(s)
    if dw >= width:
        return s
    pad_len = width - dw
    if align == ">":
        return " " * pad_len + s
    else:
        return s + " " * pad_len


def sep_line(col_widths: list[int]) -> str:
    """Draw a separator line under header."""
    parts = ["─" * w for w in col_widths]
    return "  " + "  ".join(parts) + "  ─" * 20


def fmt_num(val, width: int, decimals: int) -> str:
    """Format a number for right-aligned display."""
    if pd.isna(val):
        return f"{'—':>{width}}"
    return f"{float(val):>{width}.{decimals}f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="显示最近 N 天的交易记录")
    parser.add_argument("--days", "-d", type=int, default=7,
                        help="显示最近多少天的记录（默认 7）")
    parser.add_argument("--product", "-p", default=None,
                        help="只显示指定产品代码（可选）")
    parser.add_argument("--type", "-t", choices=["buy", "sell", "dividend"],
                        default=None, help="只显示指定交易类型（可选）")
    args = parser.parse_args()

    cutoff = pd.Timestamp(datetime.now().date() - timedelta(days=args.days))

    rows = []
    for csv_path in sorted(PORTFOLIO_DIR.glob("*.csv")):
        if csv_path.stem == "template":
            continue
        if args.product and csv_path.stem != args.product:
            continue
        df = pd.read_csv(csv_path, parse_dates=["date"], dtype={"product": str})
        recent = df[df["date"] >= cutoff]
        rows.extend(row for _, row in recent.iterrows())

    if not rows:
        product_hint = f" {args.product}" if args.product else ""
        print(f"最近 {args.days} 天无{product_hint}交易记录。")
        return

    rows.sort(key=lambda r: r["date"], reverse=True)

    col_widths = [w for _, w, _ in COLUMNS]

    print(f"\n  📋 最近 {args.days} 天交易记录")
    # Header
    header_cells = [pad(h, w, "<") for h, w, _ in COLUMNS]
    print("  " + "  ".join(header_cells) + "  备注")
    print("  " + "  ".join("─" * w for w in col_widths) + "  " + "─" * 30)

    type_labels = {"buy": "买入", "sell": "卖出", "dividend": "分红"}
    total_in = total_out = 0.0

    for row in rows:
        txn_type = str(row["type"])
        if args.type and txn_type != args.type:
            continue

        date_str = row["date"].strftime("%Y-%m-%d")
        product = str(row["product"])
        label = type_labels.get(txn_type, txn_type)
        amount = float(row["amount"])
        price = row.get("price")
        shares = row.get("shares")
        fee = row.get("fee", 0) or 0
        notes = str(row.get("notes", "") or "")

        cells = [
            pad(date_str,     10, "<"),
            pad(product,       6, "<"),
            pad(label,         6, "<"),
            f"{amount:>8.2f}",
            fmt_num(price,     8, 4),
            fmt_num(shares,    8, 2),
            f"{float(fee):>6.2f}",
        ]
        print("  " + "  ".join(cells) + f"  {notes}")

        if txn_type in ("buy", "dividend") and amount > 0:
            total_in += amount
        elif txn_type == "sell":
            total_out += amount

    # Summary
    print("  " + "  ".join("─" * w for w in col_widths) + "  " + "─" * 30)
    net = total_in - total_out
    sign = "+" if net >= 0 else ""
    print(f"\n  买入:   ¥{total_in:>10.2f}")
    print(f"  卖出:   ¥{total_out:>10.2f}")
    print(f"  净流入: ¥{sign}{net:>9.2f}\n")


if __name__ == "__main__":
    main()
