#!/usr/bin/env python3
"""Portfolio analysis CLI.

Usage:
    python scripts/portfolio_report.py                 # 所有产品
    python scripts/portfolio_report.py 002611          # 单个产品
    python scripts/portfolio_report.py 002611 --no-html
    python scripts/portfolio_report.py --refresh       # 所有产品强制刷新
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from Quantfolio.portfolio.tracker import PortfolioTracker


def _list_products() -> list[str]:
    """Scan data/portfolio/ for CSV files, return product codes."""
    portfolio_dir = Path(__file__).resolve().parent.parent / "data" / "portfolio"
    codes = []
    for f in sorted(portfolio_dir.glob("*.csv")):
        if f.name == "template.csv":
            continue
        codes.append(f.stem)
    return codes


def main() -> None:
    parser = argparse.ArgumentParser(description="Quantfolio Portfolio Analysis")
    parser.add_argument(
        "product_code",
        nargs="?",
        help="Fund product code (e.g., 002611). Omit to run all products.",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="Skip saving HTML chart",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-fetch NAV from akshare (ignore cache)",
    )
    args = parser.parse_args()

    products = [args.product_code] if args.product_code else _list_products()
    if not products:
        print("No portfolio data found.")
        return

    tracker = PortfolioTracker()
    for i, code in enumerate(products):
        if len(products) > 1:
            print(f"\n{'=' * 55}")
            print(f"  [{i + 1}/{len(products)}] {code}")
            print(f"{'=' * 55}")
        try:
            tracker.generate_report(
                product_code=code,
                save_html=not args.no_html,
                force_refresh=args.refresh,
            )
        except Exception as e:
            print(f"  [ERROR] {code}: {e}")


if __name__ == "__main__":
    main()
