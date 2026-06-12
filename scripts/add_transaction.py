#!/usr/bin/env python3
"""Add a portfolio transaction with auto-filled price/shares/fee.

Two modes:

1. Add a single transaction via CLI:
   python scripts/add_transaction.py --date 2026-05-27 --product 002611 \\
       --type buy --amount 10000 --notes "定投"

2. Fill incomplete rows in CSV files (rows with missing price/shares/fee):
   python scripts/add_transaction.py --fill [product_code]

   When product_code is omitted, all CSVs are processed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from Quantfolio.config import QuantfolioConfig
from Quantfolio.portfolio.fees import compute_buy, compute_sell
from Quantfolio.portfolio.models import Transaction
from Quantfolio.portfolio.tracker import PortfolioTracker


def fetch_nav_on_date(product: str, target_date: str, allow_fallback: bool = True) -> float | None:
    """Fetch NAV for *product* on *target_date*. Returns None if unavailable.

    When *allow_fallback* is False, only exact date match is accepted — no
    fallback to prior trading day.  Use False in ``add`` (record intent, don't
    guess) and True in ``fill`` (complete past data where weekends/holidays
    legitimately need the prior day's NAV).
    """
    tracker = PortfolioTracker()
    try:
        nav_df = tracker.fetch_nav(product)
    except Exception:
        print(f"  [ERROR] 无法获取 {product} 净值数据，请检查网络或产品代码")
        return None

    target = pd.Timestamp(target_date)
    # Try exact match first
    match = nav_df[nav_df["date"] == target]
    if not match.empty:
        return float(match.iloc[0]["nav"])

    if not allow_fallback:
        print(f"  [INFO] {target_date} 净值暂未公布，稍后运行 fill 补全")
        return None

    # Only fallback for weekends (Sat=5, Sun=6).  For weekdays without NAV
    # (today before publish, QDII T+1 delay) skip so the user can retry later.
    if target.dayofweek < 5:
        print(f"  [INFO] {target_date} 净值暂未公布（交易日），稍后重试 fill")
        return None

    # Weekend / holiday fallback: closest date before target
    before = nav_df[nav_df["date"] <= target]
    if before.empty:
        print(f"  [ERROR] {product} 在 {target_date} 及之前都没有净值数据")
        return None

    closest = before.iloc[-1]
    print(f"  [INFO] {target_date} 是周末，使用最近交易日 {closest['date'].strftime('%Y-%m-%d')} 净值 {closest['nav']:.4f}")
    return float(closest["nav"])


def load_existing_txns(product: str, cfg: QuantfolioConfig) -> list[Transaction]:
    """Load completed transactions (those with valid price) from CSV."""
    csv_path = cfg.portfolio_dir_abs / f"{product}.csv"
    if not csv_path.exists():
        return []

    df = pd.read_csv(csv_path, parse_dates=["date"], dtype={"product": str})
    txns: list[Transaction] = []
    for _, row in df.iterrows():
        price = row.get("price", None)
        if pd.isna(price) or price == 0:
            continue
        try:
            txns.append(Transaction(
                date=row["date"],
                product=str(row["product"]),
                type=str(row["type"]),
                amount=float(row["amount"]),
                price=float(price),
                shares=float(row["shares"]),
                fee=float(row.get("fee", 0) or 0),
                notes=str(row.get("notes", "") or ""),
            ))
        except (ValueError, KeyError):
            continue
    return txns


def append_transaction(
    date: str,
    product: str,
    txn_type: str,
    amount: float,
    price: float,
    shares: float,
    fee: float,
    notes: str,
    cfg: QuantfolioConfig,
) -> Path:
    """Append a row to the product CSV."""
    csv_path = cfg.portfolio_dir_abs / f"{product}.csv"
    exists = csv_path.exists()

    row = pd.DataFrame([{
        "date": date,
        "product": product,
        "type": txn_type,
        "amount": amount,
        "price": price,
        "shares": shares,
        "fee": fee,
        "notes": notes,
    }])

    if exists:
        existing = pd.read_csv(csv_path, dtype={"product": str})
        df = pd.concat([existing, row], ignore_index=True)
        df = df.sort_values("date").reset_index(drop=True)
        df.to_csv(csv_path, index=False)
    else:
        row.to_csv(csv_path, index=False)

    return csv_path


def add_single(args) -> None:
    """Add one transaction from CLI arguments.

    When exact NAV is not yet available the row is written with blank
    price/shares/fee — run ``fill`` later to complete it.
    """
    cfg = QuantfolioConfig()
    date = args.date
    product = args.product
    txn_type = args.type
    amount = args.amount
    known_fee = args.fee
    notes = args.notes or ""

    # Don't fallback: if exact date NAV isn't available, leave blank for fill
    price = fetch_nav_on_date(product, date, allow_fallback=False)

    if price is None:
        # Write placeholder row with blank price/shares/fee for fill to complete
        csv_path = cfg.portfolio_dir_abs / f"{product}.csv"
        exists = csv_path.exists()
        with open(csv_path, "a", newline="") as f:
            import csv as csv_mod
            writer = csv_mod.writer(f)
            if not exists:
                writer.writerow(["date", "product", "type", "amount", "price", "shares", "fee", "notes"])
            writer.writerow([date, product, txn_type, amount, "", "", "", notes])
        print(f"  ✓ 已添加交易记录到 {csv_path}（净值待补全）")
        print(f"    日期: {date}  产品: {product}  类型: {txn_type}")
        print(f"    金额: ¥{amount:,.2f}  ⚠️ 净值未出，稍后运行 fill 补全")
        return

    if txn_type == "buy":
        shares, fee = compute_buy(amount, price, product, known_fee)
    else:
        txns = load_existing_txns(product, cfg)
        result = compute_sell(amount, price, product, txns, date, known_fee)
        if result is None:
            print(f"  [ERROR] {product} 当前无持仓，无法卖出")
            sys.exit(1)
        shares, fee = result

    csv_path = append_transaction(date, product, txn_type, amount, price, shares, fee, notes, cfg)

    print(f"  ✓ 已添加交易记录到 {csv_path}")
    print(f"    日期: {date}  产品: {product}  类型: {txn_type}")
    print(f"    金额: ¥{amount:,.2f}  净值: ¥{price:.4f}  份额: {shares:,.2f}  手续费: ¥{fee:.2f}")


def fill_incomplete(args) -> None:
    """Fill rows with missing price/shares/fee in chronological order."""
    cfg = QuantfolioConfig()
    products = [args.product_code] if args.product_code else [
        p.stem for p in cfg.portfolio_dir_abs.glob("*.csv")
        if p.stem != "template"
    ]

    for product in products:
        csv_path = cfg.portfolio_dir_abs / f"{product}.csv"
        if not csv_path.exists():
            print(f"  [SKIP] {csv_path} 不存在")
            continue

        df = pd.read_csv(csv_path, parse_dates=["date"], dtype={"product": str})
        if df.empty:
            continue

        changed = False
        completed_txns = load_existing_txns(product, cfg)

        for idx in range(len(df)):
            row = df.iloc[idx]
            if str(row.get("type", "")).strip() == "dividend":
                continue  # 分红行由用户手动填写，不需要自动计算
            has_price = pd.notna(row.get("price")) and row["price"] != 0
            has_shares = pd.notna(row.get("shares")) and row["shares"] != 0
            raw_fee = row.get("fee", 0)
            has_fee = pd.notna(raw_fee) and raw_fee != 0
            if has_price and has_shares and not has_fee:
                continue  # 完整且无手续费的行跳过；有手续费时需用手续费重算份额

            target_date = str(row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else row["date"])[:10]
            txn_type = str(row["type"]).strip()
            amount = float(row["amount"])
            notes = str(row.get("notes", "") or "")

            price = fetch_nav_on_date(product, target_date)
            if price is None:
                print(f"  [WARN] 跳过 {product} 第{idx + 2}行: 无法获取净值")
                continue

            known_fee = float(raw_fee) if pd.notna(raw_fee) and raw_fee != 0 else None

            if txn_type == "buy":
                shares, fee = compute_buy(amount, price, product, known_fee)
            else:
                result = compute_sell(amount, price, product, completed_txns, target_date, known_fee)
                if result is None:
                    print(f"  [WARN] 跳过 {product} 第{idx + 2}行: 持仓不足")
                    continue
                shares, fee = result

            df.at[idx, "price"] = price
            df.at[idx, "shares"] = shares
            df.at[idx, "fee"] = fee
            changed = True

            completed_txns.append(Transaction(
                date=pd.Timestamp(target_date),
                product=product,
                type=txn_type,
                amount=amount,
                price=price,
                shares=shares,
                fee=fee,
                notes=notes,
            ))
            # Keep sorted by date for FIFO correctness
            completed_txns.sort(key=lambda t: t.date)

            print(f"  ✓ {product} {target_date} {txn_type}: amount={amount} -> price={price:.4f} shares={shares:.2f} fee={fee:.2f}")

        if changed:
            df = df.sort_values("date").reset_index(drop=True)
            df.to_csv(csv_path, index=False)
            print(f"  ✓ 已更新 {csv_path}")
        else:
            print(f"  = {product}: 无需补全")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="添加基金交易记录，自动计算净值/份额/手续费",
    )
    sub = parser.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="添加单笔交易")
    p_add.add_argument("--date", required=True, help="交易日期 YYYY-MM-DD")
    p_add.add_argument("--product", required=True, help="基金代码")
    p_add.add_argument("--type", required=True, choices=["buy", "sell"], help="buy 或 sell")
    p_add.add_argument("--amount", type=float, required=True, help="金额（买入含手续费，卖出为到账金额）")
    p_add.add_argument("--fee", type=float, default=None, help="手续费（可选，不传则按费率表自动计算）")
    p_add.add_argument("--notes", default="", help="备注（可选）")

    # fill
    p_fill = sub.add_parser("fill", help="补全 CSV 中缺失的 price/shares/fee")
    p_fill.add_argument("product_code", nargs="?", default=None, help="基金代码（可选，默认处理所有）")

    args = parser.parse_args()

    if args.command == "add":
        add_single(args)
    elif args.command == "fill":
        fill_incomplete(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
