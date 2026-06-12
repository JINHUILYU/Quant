#!/usr/bin/env python3
"""Portfolio analysis CLI.

Usage:
    python scripts/portfolio_report.py <product_code>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from Quantfolio.portfolio.tracker import PortfolioTracker


def main() -> None:
    parser = argparse.ArgumentParser(description="Quantfolio Portfolio Analysis")
    parser.add_argument(
        "product_code",
        help="Fund product code (e.g., 002611 for 博时黄金ETF联接C)",
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

    tracker = PortfolioTracker()
    tracker.generate_report(
        product_code=args.product_code,
        save_html=not args.no_html,
        force_refresh=args.refresh,
    )


if __name__ == "__main__":
    main()
