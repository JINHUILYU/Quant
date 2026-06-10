#!/usr/bin/env python3
"""Market opportunity scanner — find oversold sectors, big ETF movers, and potential entry points.

Usage:
    python scripts/market_scan.py              # Full scan (ETF losers + sectors + themes)
    python scripts/market_scan.py --etf-only   # Only ETF losers
    python scripts/market_scan.py --sector-only # Only sector/industry scan
    python scripts/market_scan.py --top 10     # Show top/bottom 10 (default 8)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

# Suppress akshare's tqdm progress bars in output
import tqdm as _tqdm
_tqdm.tqdm.pandas = lambda *a, **kw: a[0] if a else None
import functools
_orig_init = _tqdm.tqdm.__init__
@functools.wraps(_orig_init)
def _quiet_init(self, *a, **kw):
    kw.setdefault("disable", True)
    _orig_init(self, *a, **kw)
_tqdm.tqdm.__init__ = _quiet_init

# ── Display helpers ──────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

import re
import unicodedata

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _display_width(s: str) -> int:
    """Terminal display width: CJK/emoji → 2, ASCII → 1, ANSI codes → 0."""
    s = _ANSI_RE.sub("", s)
    w = 0
    for c in s:
        # Skip zero-width characters: nonspacing marks (variation selectors,
        # combining chars), format chars (ZWJ, ZWNJ, etc.)
        cat = unicodedata.category(c)
        if cat in ("Mn", "Cf"):
            continue
        w += 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
    return w


def _lpad(s: str, width: int) -> str:
    """Left-pad to *display* width (i.e. right-align)."""
    return " " * max(0, width - _display_width(s)) + s


def _rpad(s: str, width: int) -> str:
    """Right-pad to *display* width (i.e. left-align)."""
    return s + " " * max(0, width - _display_width(s))


def _truncate(s: str, width: int) -> str:
    """Truncate to fit within *display* width."""
    dw = 0
    result = []
    for c in s:
        cat = unicodedata.category(c)
        if cat in ("Mn", "Cf"):
            result.append(c)  # always keep zero-width chars
            continue
        cw = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if dw + cw > width:
            break
        dw += cw
        result.append(c)
    return "".join(result)


def _color_chg(val: float) -> str:
    if val > 0:
        return f"{GREEN}{val:+.2f}%{RESET}"
    elif val < 0:
        return f"{RED}{val:.2f}%{RESET}"
    return f"{DIM} 0.00%{RESET}"


# ── Data fetchers ───────────────────────────────────────────────────────

def _fetch_etfs() -> pd.DataFrame:
    import akshare as ak
    return ak.fund_etf_spot_em()


def _fetch_sectors() -> pd.DataFrame | None:
    """Fetch sector/board performance (uses push2ex CDN, more reliable)."""
    import akshare as ak
    try:
        return ak.stock_board_change_em()
    except Exception:
        return None


# ── Scanners ──────────────────────────────────────────────────────────────

def scan_etf_losers(top_n: int = 8) -> pd.DataFrame | None:
    """Find ETFs with biggest daily declines. Returns ranked DataFrame or None."""
    print(f"\n  {BOLD}📉 ETF 跌幅榜 Top {top_n}{RESET}\n")

    try:
        df = _fetch_etfs()
    except Exception as e:
        print(f"  {DIM}ETF 数据获取失败: {e}{RESET}")
        return None

    chg_col = "涨跌幅"
    if chg_col not in df.columns:
        return None

    df["_chg"] = pd.to_numeric(df[chg_col], errors="coerce")

    # Exclude money-market / bond ETFs (they don't move meaningfully)
    skip_kw = ["日利", "添益", "货币", "短融", "债", "回购"]
    mask = ~df["名称"].str.contains("|".join(skip_kw), na=False)
    losers = df[mask].nsmallest(top_n, "_chg")

    CODE_W, NAME_W, PRICE_W, CHG_W = 8, 28, 10, 10
    # Build header so we can measure its display width for the separator
    hdr = f"{_lpad('代码', CODE_W)}  {_rpad('名称', NAME_W)} {_lpad('最新价', PRICE_W)} {_lpad('涨跌幅', CHG_W)}"
    print(f"  {DIM}{hdr}{RESET}")
    print("  " + "─" * _display_width(hdr))

    for _, r in losers.iterrows():
        code = _lpad(str(r.get("代码", "")), CODE_W)
        name = _rpad(_truncate(str(r.get("名称", "")), NAME_W), NAME_W)
        price = _lpad(str(r.get("最新价", "-")), PRICE_W)
        chg_str = _lpad(_color_chg(r["_chg"]), CHG_W)
        print(f"  {code}  {name} {price} {chg_str}")

    print()
    return losers


def scan_sector_losers(top_n: int = 8) -> pd.DataFrame | None:
    """Find industry/concept sectors with biggest declines. Returns ranked DataFrame or None."""
    print(f"\n  {BOLD}🏭 弱势板块 Top {top_n}{RESET}\n")

    df = _fetch_sectors()
    if df is None:
        print(f"  {DIM}板块数据获取失败{RESET}\n")
        return None

    if "板块名称" not in df.columns or "涨跌幅" not in df.columns:
        print(f"  {DIM}板块数据格式异常: {df.columns.tolist()}{RESET}\n")
        return None

    df["_chg"] = pd.to_numeric(df["涨跌幅"], errors="coerce")

    # Filter out meta/derived boards — keep only real industries
    noise_kw = ["昨日", "融资", "融券", "风格", "振幅", "破净", "活跃",
                "高贝", "低市", "亏损", "微盘", "打板", "连板", "昨日涨停"]
    mask = ~df["板块名称"].str.contains("|".join(noise_kw), na=False)
    real_sectors = df[mask]

    # Dedup — same board name can appear in both 行业 and 概念 categories.
    # Sort by _chg ascending first so we keep the weaker (more negative) entry.
    real_sectors = real_sectors.sort_values("_chg").drop_duplicates(subset=["板块名称"])
    losers = real_sectors.nsmallest(top_n, "_chg")

    NAME_W, CHG_W = 18, 10
    hdr = f"{_rpad('板块', NAME_W)} {_lpad('涨跌幅', CHG_W)}"
    print(f"  {DIM}{hdr}{RESET}")
    print("  " + "─" * _display_width(hdr))

    for _, r in losers.iterrows():
        name = _rpad(_truncate(str(r["板块名称"]), NAME_W), NAME_W)
        chg_str = _lpad(_color_chg(r["_chg"]), CHG_W)
        print(f"  {name} {chg_str}")

    print()
    return losers


def scan_themes() -> None:
    """Identify thematic clusters: what's hot, what's cold."""
    print(f"\n  {BOLD}🔬 主题热点扫描{RESET}\n")

    # ── ETF volume leaders (where money is flowing) ──
    try:
        etfs = _fetch_etfs()
    except Exception:
        print(f"  {DIM}ETF 数据不可用{RESET}\n")
        return

    etfs["_chg"] = pd.to_numeric(etfs["涨跌幅"], errors="coerce")

    # Top gainers (themes in motion)
    skip_kw = ["日利", "添益", "货币", "短融", "债", "回购"]
    mask = ~etfs["名称"].str.contains("|".join(skip_kw), na=False)
    active = etfs[mask].copy()

    gainers = active.nlargest(5, "_chg")

    print(f"  {BOLD}🔥 今日主线（涨幅 Top 5）{RESET}")
    NAME_W, CHG_W = 28, 8
    hdr = f"{_rpad('ETF', NAME_W)} {_lpad('涨跌幅', CHG_W)}"
    print(f"  {DIM}{hdr}{RESET}")
    print("  " + "─" * _display_width(hdr))
    for _, r in gainers.iterrows():
        name = _rpad(_truncate(str(r.get("名称", "")), NAME_W), NAME_W)
        print(f"  {name} {_lpad(_color_chg(r['_chg']), CHG_W)}")

    # ── Sector clusters ──
    df = _fetch_sectors()
    if df is not None and "板块名称" in df.columns and "涨跌幅" in df.columns:
        df["_chg"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
        noise_kw = ["昨日", "融资", "融券", "风格", "振幅", "破净", "活跃",
                    "高贝", "低市", "亏损", "微盘", "打板", "连板", "昨日涨停"]
        real = df[~df["板块名称"].str.contains("|".join(noise_kw), na=False)]

        print(f"\n  {BOLD}📊 行业轮动概览{RESET}\n")

        # Group by rough category
        categories = {
            "🛢️ 能源/资源": ["油气", "石油", "煤炭", "焦炭", "能源", "油服", "采矿"],
            "🔬 科技/半导体": ["半导体", "芯片", "电子", "通信", "5G", "计算机", "AI", "软件"],
            "🏥 医药/医疗": ["医药", "医疗", "生物", "制药", "创新药", "中药", "器械"],
            "🍶 消费/白酒": ["白酒", "食品", "饮料", "家电", "消费", "零售"],
            "🏦 金融/地产": ["银行", "保险", "证券", "地产", "金融"],
            "🏭 制造/周期": ["化工", "钢铁", "有色", "建材", "机械", "电力"],
            "🚗 汽车/新能源": ["汽车", "新能源", "锂电", "光伏", "电池"],
        }

        for label, keywords in categories.items():
            matched = real[real["板块名称"].str.contains("|".join(keywords), na=False)]
            if matched.empty:
                continue
            avg_chg = matched["_chg"].mean()
            best = matched.loc[matched["_chg"].idxmax()]
            worst = matched.loc[matched["_chg"].idxmin()]
            bar = "🟢" if avg_chg > 1 else ("🟡" if avg_chg > -1 else "🔴")
            label_col = _rpad(label, 18)
            chg_col = _lpad(_color_chg(avg_chg), 8)
            best_col = _rpad(_truncate(str(best["板块名称"]), 10), 10)
            worst_col = _rpad(_truncate(str(worst["板块名称"]), 10), 10)
            print(f"  {bar} {label_col} 均值 {chg_col}  领涨: {best_col} 领跌: {worst_col}")

    print()


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="市场机会扫描 — 寻找超跌板块和潜在加仓机会")
    parser.add_argument("--etf-only", action="store_true", help="只扫描 ETF 跌幅榜")
    parser.add_argument("--sector-only", action="store_true", help="只扫描行业板块")
    parser.add_argument("--top", type=int, default=8, help="显示 Top N (默认 8)")
    args = parser.parse_args()

    print()
    print(f"  ╔{'═' * 52}╗")
    print(f"  ║                    🔍 市场机会扫描                 ║")
    print(f"  ╚{'═' * 52}╝")

    if args.sector_only:
        scan_sector_losers(args.top)
    elif args.etf_only:
        scan_etf_losers(args.top)
    else:
        scan_etf_losers(args.top)
        time.sleep(0.5)
        scan_sector_losers(args.top)
        time.sleep(0.5)
        scan_themes()

    print(f"  {DIM}数据基于实时行情，仅供研究参考，不构成投资建议。{RESET}\n")


if __name__ == "__main__":
    main()
