#!/usr/bin/env python3
"""Real-time market snapshot with portfolio cross-reference.

Usage:
    python scripts/market_snapshot.py           # 完整快照
    python scripts/market_snapshot.py --brief   # 简洁版
    python scripts/market_snapshot.py --gold    # 只看黄金
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd


# ── Data fetchers ────────────────────────────────────────────────────────

def _fetch_indices() -> pd.DataFrame:
    import akshare as ak

    return ak.stock_zh_index_spot_em()


def _fetch_etfs() -> pd.DataFrame:
    import akshare as ak

    return ak.fund_etf_spot_em()


# ── Display helpers ──────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _color(val: float) -> str:
    if val > 0:
        return f"{GREEN}+{val:.2f}%{RESET}"
    elif val < 0:
        return f"{RED}{val:.2f}%{RESET}"
    return " 0.00%"


def _sign(val: float) -> str:
    if val > 0:
        return f"{GREEN}▲{RESET}"
    elif val < 0:
        return f"{RED}▼{RESET}"
    return "─"


# ── Core display ─────────────────────────────────────────────────────────

def show_gold(etfs: pd.DataFrame) -> None:
    """Gold ETFs and Au99.99 proxy."""
    gold_etfs = {
        "518880": "华安黄金ETF（→000217联接）",
        "518800": "国泰黄金ETF（→004253联接）",
        "518600": "广发上海金ETF（→008987联接）",
        "518850": "华夏黄金ETF（→008701联接）",
    }
    print(f"\n  {BOLD}🥇 黄金 ETF 实时行情{RESET}")
    print(f"  {'代码':<8} {'名称':<28} {'最新价':>8} {'涨跌幅':>10}")
    print("  " + "─" * 58)
    for _, r in etfs.iterrows():
        code = str(r.get("代码", ""))
        if code in gold_etfs:
            price = r.get("最新价", "-")
            chg = r.get("涨跌幅", 0)
            try:
                chg_f = float(chg) if chg and chg != "-" else 0.0
            except (ValueError, TypeError):
                chg_f = 0.0
            c = _color(chg_f)
            print(f"  {code:<8} {gold_etfs[code]:<28} {str(price):>8}  {c}")
    print()


def show_key_indices(indices: pd.DataFrame) -> None:
    """Filter to indices relevant to portfolio."""
    KEYWORDS = [
        "上证指数", "沪深300", "上证50", "科创50", "科创芯片",
        "创业板指", "深证成指", "上证综合全收益",
    ]
    print(f"  {BOLD}📊 关键指数{RESET}")
    print(f"  {'名称':<16} {'最新':>10} {'涨跌幅':>10} {'方向':>4}")
    print("  " + "─" * 46)
    shown = set()
    for _, r in indices.iterrows():
        name = str(r.get("名称", ""))
        for kw in KEYWORDS:
            if kw in name and name not in shown:
                shown.add(name)
                price = r.get("最新价", "-")
                chg_raw = r.get("涨跌幅", 0)
                try:
                    chg = float(chg_raw) if chg_raw else 0.0
                except (ValueError, TypeError):
                    chg = 0.0
                arrow = _sign(chg)
                c = _color(chg)
                print(f"  {name:<16} {str(price):>10}  {c}  {arrow}")
                break
    print()


def show_portfolio_etfs(etfs: pd.DataFrame) -> None:
    """ETFs corresponding to feeder funds in portfolio."""
    # ETF spot codes for funds the user holds (via feeder fund tracking)
    RELEVANT = {
        "159941": "纳指ETF（→019548/016452联接）",
        "513100": "纳指100ETF（→016452联接）",
        "510300": "沪深300ETF（→110020联接）",
        "510050": "上证50ETF（→006220联接）",
        "588000": "科创50ETF（→半导体相关）",
        "159994": "5G通信ETF",
        "161226": "白银LOF（→161226）",
    }
    print(f"  {BOLD}🔗 持仓关联 ETF{RESET}")
    print(f"  {'代码':<8} {'名称':<28} {'最新价':>8} {'涨跌幅':>10}")
    print("  " + "─" * 58)
    for _, r in etfs.iterrows():
        code = str(r.get("代码", ""))
        if code in RELEVANT:
            price = r.get("最新价", "-")
            chg = r.get("涨跌幅", 0)
            try:
                chg_f = float(chg) if chg and chg != "-" else 0.0
            except (ValueError, TypeError):
                chg_f = 0.0
            c = _color(chg_f)
            print(f"  {code:<8} {RELEVANT[code]:<28} {str(price):>8}  {c}")
    print()


def show_summary(indices: pd.DataFrame, etfs: pd.DataFrame) -> None:
    """One-line verdict."""
    # Get key signals
    sh = indices[indices["名称"].str.contains("上证指数", na=False)]
    hs300 = indices[indices["名称"].str.contains("沪深300", na=False)]
    kc50 = indices[indices["名称"].str.contains("科创50", na=False)]
    kc_chip = indices[indices["名称"].str.contains("科创芯片", na=False)]

    sh_chg = float(sh["涨跌幅"].iloc[0]) if not sh.empty else 0
    hs_chg = float(hs300["涨跌幅"].iloc[0]) if not hs300.empty else 0
    kc_chg = float(kc50["涨跌幅"].iloc[0]) if not kc50.empty else 0
    chip_chg = float(kc_chip["涨跌幅"].iloc[0]) if not kc_chip.empty else 0

    gold_etf = etfs[etfs["代码"] == "518880"]
    gold_chg = float(gold_etf["涨跌幅"].iloc[0]) if not gold_etf.empty else 0

    print(f"  {BOLD}📝 一句话总结{RESET}")
    parts = []
    if sh_chg > 0.3:
        parts.append(f"大盘{_color(sh_chg)} 偏强")
    elif sh_chg < -0.3:
        parts.append(f"大盘{_color(sh_chg)} 偏弱")
    else:
        parts.append(f"大盘{_color(sh_chg)} 横盘")

    if gold_chg > 0.1:
        parts.append(f"黄金{_color(gold_chg)}")
    elif gold_chg < -0.1:
        parts.append(f"黄金{_color(gold_chg)}")
    else:
        parts.append("黄金横盘")

    if chip_chg < -1:
        parts.append(f"半导体{_color(chip_chg)} 承压")
    elif chip_chg > 1:
        parts.append(f"半导体{_color(chip_chg)} 强势")

    print(f"  {' | '.join(parts)}")

    # Quick action hints
    print(f"\n  {BOLD}💡 操作参考{RESET}")
    if gold_chg > 0.5:
        print(f"  黄金 ETF 上涨，现有仓位持有，不宜追高")
    elif gold_chg < -0.5:
        print(f"  黄金 ETF 回调，关注是否接近支撑位，可考虑分批加仓")
    else:
        print(f"  黄金 ETF 窄幅波动，观望为主")

    if abs(chip_chg) > 2:
        print(f"  半导体波动较大（{_color(chip_chg)}），519674 仓位小，无需恐慌")
    print()


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="实时行情快照")
    parser.add_argument("--brief", action="store_true", help="简洁模式")
    parser.add_argument("--gold", action="store_true", help="只看黄金")
    args = parser.parse_args()

    print()
    print(f"  ╔{'═' * 52}╗")
    print(f"  ║  📡 实时行情快照                                        ║")
    print(f"  ╚{'═' * 52}╝")

    try:
        etfs = _fetch_etfs()
    except Exception as e:
        print(f"  [ERROR] 获取 ETF 数据失败: {e}")
        return

    if args.gold:
        show_gold(etfs)
        return

    try:
        indices = _fetch_indices()
    except Exception as e:
        print(f"  [ERROR] 获取指数数据失败: {e}")
        return

    if args.brief:
        show_summary(indices, etfs)
        return

    show_gold(etfs)
    show_key_indices(indices)
    show_portfolio_etfs(etfs)
    show_summary(indices, etfs)


if __name__ == "__main__":
    main()
