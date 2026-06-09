#!/usr/bin/env python3
"""Real-time market snapshot with portfolio cross-reference.

Usage:
    python scripts/market_snapshot.py           # 完整快照
    python scripts/market_snapshot.py --brief   # 简洁版（仅总结+操作建议）
    python scripts/market_snapshot.py --gold    # 只看黄金
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd


# ── Data fetchers ────────────────────────────────────────────────────────

import time
import random
import requests


def _with_browser_headers(func):
    """Context manager: patch requests with browser User-Agent to avoid 430/blocking."""
    original_get = requests.get
    original_post = requests.post

    def _patched(method, url, **kwargs):
        headers = kwargs.get("headers") or {}
        headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8")
        headers.setdefault("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
        kwargs["headers"] = headers
        return method(url, **kwargs)

    try:
        requests.get = lambda url, **kw: _patched(original_get, url, **kw)
        requests.post = lambda url, **kw: _patched(original_post, url, **kw)
        return func()
    finally:
        requests.get = original_get
        requests.post = original_post


def _retry(func, name: str, max_retries: int = 3, base_delay: float = 2.0):
    """Retry with exponential backoff + jitter on connection errors."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"  [RETRY] {name} 第 {attempt + 1} 次重试，等待 {delay:.1f}s...")
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _fetch_indices() -> pd.DataFrame:
    import akshare as ak

    try:
        return _retry(lambda: _with_browser_headers(ak.stock_zh_index_spot_em), "指数数据(EM)")
    except Exception:
        print(f"  [INFO] 东方财富指数接口不可用，切换新浪数据源...")
        return _retry(lambda: ak.stock_zh_index_spot_sina(), "指数数据(Sina)")


def _fetch_etfs() -> pd.DataFrame:
    import akshare as ak

    return _retry(lambda: ak.fund_etf_spot_em(), "ETF 数据")


def _fetch_lofs() -> pd.DataFrame | None:
    """Fetch LOF spot data (for 白银LOF etc). Returns None on failure."""
    import akshare as ak

    try:
        return _retry(
            lambda: _with_browser_headers(ak.fund_lof_spot_em),
            "LOF 数据",
            max_retries=2,
            base_delay=1.5,
        )
    except Exception as e:
        print(f"  [WARN] LOF 数据(Eastmoney)获取失败: {e}")

    # Fallback: Sina LOF data
    try:
        df = _retry(
            lambda: ak.fund_etf_category_sina(symbol="LOF基金"),
            "LOF 数据(Sina)",
            max_retries=2,
            base_delay=1.5,
        )
        # Normalize codes: Sina uses "sz161226" / "sh501018", strip exchange prefix
        if "代码" in df.columns:
            import re
            df["代码"] = df["代码"].str.replace(r"^(sz|sh)", "", regex=True)
        return df
    except Exception as e2:
        print(f"  [WARN] LOF 数据(Sina)获取也失败: {e2}")
        return None


def _validate_sector_df(df: pd.DataFrame | None, label: str) -> pd.DataFrame | None:
    """Validate that *df* has columns recognized by show_sector_leaders."""
    if df is None:
        return None
    if _find_col(df, ["板块名称", "名称", "name", "行业名称"]) is None or \
       _find_col(df, ["涨跌幅", "涨幅", "change_pct", "涨跌幅(%)"]) is None:
        print(f"  [WARN] {label}返回格式异常: {df.columns.tolist()}, 跳过")
        return None
    return df


def _fetch_industry_sectors() -> pd.DataFrame | None:
    """Fetch industry sector performance. Returns None on failure."""
    import akshare as ak

    # Primary: Eastmoney stock_board_industry_spot_em
    try:
        df = _retry(
            lambda: _with_browser_headers(ak.stock_board_industry_spot_em),
            "行业板块数据",
            max_retries=2,
            base_delay=1.5,
        )
        if (validated := _validate_sector_df(df, "行业板块主源")) is not None:
            return validated
    except Exception as e:
        print(f"  [WARN] 行业板块数据(Eastmoney)获取失败: {e}")

    # Fallback: stock_board_change_em (uses push2ex.eastmoney.com, different CDN)
    try:
        df = _retry(
            lambda: ak.stock_board_change_em(),
            "行业板块数据(change_em)",
            max_retries=2,
            base_delay=1.5,
        )
        return _validate_sector_df(df, "行业板块备用源")
    except Exception as e2:
        print(f"  [WARN] 行业板块数据(change_em)获取也失败: {e2}")
        return None


def _fetch_concept_sectors() -> pd.DataFrame | None:
    """Fetch concept sector performance. Returns None on failure."""
    import akshare as ak

    # Primary: Eastmoney stock_board_concept_spot_em
    try:
        df = _retry(
            lambda: _with_browser_headers(ak.stock_board_concept_spot_em),
            "概念板块数据",
            max_retries=2,
            base_delay=1.5,
        )
        if (validated := _validate_sector_df(df, "概念板块主源")) is not None:
            return validated
    except Exception as e:
        print(f"  [WARN] 概念板块数据(Eastmoney)获取失败: {e}")

    # Fallback: stock_board_change_em (uses push2ex.eastmoney.com, different CDN)
    try:
        df = _retry(
            lambda: ak.stock_board_change_em(),
            "概念板块数据(change_em)",
            max_retries=2,
            base_delay=1.5,
        )
        return _validate_sector_df(df, "概念板块备用源")
    except Exception as e2:
        print(f"  [WARN] 概念板块数据(change_em)获取也失败: {e2}")
        return None


# ── Display helpers ──────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def _dw(s: str) -> int:
    """Display width: CJK=2, ASCII=1. Strips ANSI codes first."""
    import re
    import unicodedata
    clean = re.sub(r"\033\[[0-9;]*m", "", s)
    w = 0
    for ch in clean:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def _pad(s: str, width: int, align: str = "<") -> str:
    """Pad *s* to *display width*."""
    d = _dw(s)
    pad_width = max(0, width - d)
    if align == ">":
        return " " * pad_width + s
    return s + " " * pad_width


def _trunc(s: str, width: int) -> str:
    """Truncate to display width, preserving ANSI codes."""
    import re
    import unicodedata
    clean = re.sub(r"\033\[[0-9;]*m", "", s)
    w = 0
    result: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\033":
            end = s.index("m", i) + 1
            result.append(s[i:end])
            i = end
            continue
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > width:
            break
        result.append(ch)
        w += cw
        i += 1
    return "".join(result)


def _color_chg(val: float) -> str:
    """Colored change string."""
    if val > 0:
        return f"{GREEN}{val:+.2f}%{RESET}"
    elif val < 0:
        return f"{RED}{val:.2f}%{RESET}"
    return f"{DIM} 0.00%{RESET}"


def _color_chg_short(val: float) -> str:
    """Colored change, compact (no forced + sign for positive)."""
    if val > 0:
        return f"{GREEN}+{val:.2f}%{RESET}"
    elif val < 0:
        return f"{RED}{val:.2f}%{RESET}"
    return f"{DIM}0.00%{RESET}"


def _sign(val: float) -> str:
    if val > 0:
        return f"{GREEN}▲{RESET}"
    elif val < 0:
        return f"{RED}▼{RESET}"
    return f"{DIM}─{RESET}"


def _bar(val: float, max_val: float, width: int = 8) -> str:
    """Mini horizontal bar for visual comparison."""
    if max_val == 0:
        return ""
    ratio = abs(val) / abs(max_val)
    filled = round(ratio * width)
    if val > 0:
        return f"{GREEN}{'█' * filled}{RESET}{DIM}{'░' * (width - filled)}{RESET}"
    else:
        return f"{RED}{'█' * filled}{RESET}{DIM}{'░' * (width - filled)}{RESET}"


def _safe_float(val, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Find first matching column name from candidates."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


# ── Section display functions ────────────────────────────────────────────

def show_broad_indices(indices: pd.DataFrame) -> dict[str, float]:
    """Show broad market indices. Returns dict of key index changes for summary."""
    # Expanded list: major indices across cap sizes and styles
    TARGETS: list[tuple[str, str]] = [
        ("上证指数", "上证指数"),
        ("深证成指", "深证成指"),
        ("创业板指", "创业板指"),
        ("科创50", "科创50"),
        ("沪深300", "沪深300"),
        ("上证50", "上证50"),
        ("中证500", "中证500"),
        ("中证1000", "中证1000"),
        ("科创芯片", "科创芯片"),
    ]

    NAME_W, PRICE_W, CHG_W = 14, 10, 10

    print(f"\n  {BOLD}📊 大盘指数{RESET}")
    print(f"  {_pad('名称', NAME_W)} {_pad('最新', PRICE_W, '>')} {_pad('涨跌幅', CHG_W, '>')}")
    print("  " + "─" * (2 + NAME_W + 1 + PRICE_W + 1 + CHG_W))

    captured: dict[str, float] = {}
    shown: set[str] = set()

    for _, r in indices.iterrows():
        name = str(r.get("名称", ""))
        for keyword, label in TARGETS:
            if keyword in name and label not in shown:
                shown.add(label)
                price = str(r.get("最新价", "-"))
                chg = _safe_float(r.get("涨跌幅", 0))
                chg_str = _color_chg(chg)
                captured[label] = chg
                print(f"  {_pad(label, NAME_W)} {_pad(price, PRICE_W, '>')} {_pad(chg_str, CHG_W, '>')}")
                break

    # Try to get 恒生指数 (may not be in EM data, try different keyword)
    for _, r in indices.iterrows():
        name = str(r.get("名称", ""))
        if ("恒生" in name and "恒生" not in shown):
            shown.add("恒生")
            price = str(r.get("最新价", "-"))
            chg = _safe_float(r.get("涨跌幅", 0))
            captured["恒生指数"] = chg
            print(f"  {_pad('恒生指数', NAME_W)} {_pad(price, PRICE_W, '>')} {_pad(_color_chg(chg), CHG_W, '>')}")
            break

    print()
    return captured


def _detect_sector_columns(df: pd.DataFrame) -> tuple[str, str]:
    """Detect name and change columns in sector data."""
    name_col = _find_col(df, ["板块名称", "名称", "name", "行业名称"])
    chg_col = _find_col(df, ["涨跌幅", "涨幅", "change_pct", "涨跌幅(%)"])
    if name_col is None or chg_col is None:
        raise ValueError(f"无法识别板块数据列名，可用列: {df.columns.tolist()}")
    return name_col, chg_col


def show_sector_leaders(
    industries: pd.DataFrame | None,
    concepts: pd.DataFrame | None,
    top_n: int = 5,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Show top/bottom industry and concept sectors. Returns (top_industries, bottom_industries)."""
    top_inds: list[tuple[str, float]] = []
    bottom_inds: list[tuple[str, float]] = []

    NAME_W, CHG_W = 16, 10

    # ── Industry sectors ──
    if industries is not None and not industries.empty:
        try:
            name_col, chg_col = _detect_sector_columns(industries)
            df = industries.copy()
            df["_chg"] = pd.to_numeric(df[chg_col], errors="coerce")
            df = df.dropna(subset=["_chg"]).sort_values("_chg", ascending=False)

            print(f"  {BOLD}🏭 行业板块 ─ 今日涨幅 Top {top_n}{RESET}")
            print(f"  {_pad('板块', NAME_W)} {_pad('涨跌幅', CHG_W, '>')}   对比")
            print("  " + "─" * (2 + NAME_W + 1 + CHG_W + 4 + 10))
            top = df.head(top_n)
            max_chg = abs(top["_chg"].iloc[0]) if not top.empty else 1
            for _, r in top.iterrows():
                name = _trunc(str(r[name_col]), NAME_W)
                chg = r["_chg"]
                chg_str = _color_chg(chg)
                bar_str = _bar(chg, max_chg)
                print(f"  {_pad(name, NAME_W)} {_pad(chg_str, CHG_W, '>')}   {bar_str}")
                top_inds.append((str(r[name_col]), chg))

            print()
            print(f"  {BOLD}🏭 行业板块 ─ 今日跌幅 Top {top_n}{RESET}")
            print(f"  {_pad('板块', NAME_W)} {_pad('涨跌幅', CHG_W, '>')}   对比")
            print("  " + "─" * (2 + NAME_W + 1 + CHG_W + 4 + 10))
            bottom = df.tail(top_n).iloc[::-1]
            max_chg = abs(bottom["_chg"].iloc[0]) if not bottom.empty else 1
            for _, r in bottom.iterrows():
                name = _trunc(str(r[name_col]), NAME_W)
                chg = r["_chg"]
                chg_str = _color_chg(chg)
                bar_str = _bar(chg, max_chg)
                print(f"  {_pad(name, NAME_W)} {_pad(chg_str, CHG_W, '>')}   {bar_str}")
                bottom_inds.append((str(r[name_col]), chg))
            print()
        except Exception as e:
            print(f"  [WARN] 行业板块解析失败: {e}\n")

    # ── Concept sectors ──
    if concepts is not None and not concepts.empty:
        try:
            name_col, chg_col = _detect_sector_columns(concepts)
            df = concepts.copy()
            df["_chg"] = pd.to_numeric(df[chg_col], errors="coerce")
            df = df.dropna(subset=["_chg"]).sort_values("_chg", ascending=False)

            print(f"  {BOLD}💡 概念板块 ─ 今日涨幅 Top {top_n}{RESET}")
            print(f"  {_pad('板块', NAME_W)} {_pad('涨跌幅', CHG_W, '>')}   对比")
            print("  " + "─" * (2 + NAME_W + 1 + CHG_W + 4 + 10))
            top = df.head(top_n)
            max_chg = abs(top["_chg"].iloc[0]) if not top.empty else 1
            for _, r in top.iterrows():
                name = _trunc(str(r[name_col]), NAME_W)
                chg = r["_chg"]
                chg_str = _color_chg(chg)
                bar_str = _bar(chg, max_chg)
                print(f"  {_pad(name, NAME_W)} {_pad(chg_str, CHG_W, '>')}   {bar_str}")

            print()
            print(f"  {BOLD}💡 概念板块 ─ 今日跌幅 Top {top_n}{RESET}")
            print(f"  {_pad('板块', NAME_W)} {_pad('涨跌幅', CHG_W, '>')}   对比")
            print("  " + "─" * (2 + NAME_W + 1 + CHG_W + 4 + 10))
            bottom = df.tail(top_n).iloc[::-1]
            max_chg = abs(bottom["_chg"].iloc[0]) if not bottom.empty else 1
            for _, r in bottom.iterrows():
                name = _trunc(str(r[name_col]), NAME_W)
                chg = r["_chg"]
                chg_str = _color_chg(chg)
                bar_str = _bar(chg, max_chg)
                print(f"  {_pad(name, NAME_W)} {_pad(chg_str, CHG_W, '>')}   {bar_str}")
            print()
        except Exception as e:
            print(f"  [WARN] 概念板块解析失败: {e}\n")

    return top_inds, bottom_inds


def show_gold(etfs: pd.DataFrame) -> float:
    """Gold ETFs. Returns gold ETF change for summary."""
    gold_etfs = {
        "518880": "华安黄金ETF（→000217联接）",
        "518800": "国泰黄金ETF（→004253联接）",
        "518600": "广发上海金ETF（→008987联接）",
        "518850": "华夏黄金ETF（→008701联接）",
    }
    CODE_W, NAME_W, PRICE_W, CHG_W = 8, 32, 10, 10

    print(f"  {BOLD}🥇 黄金 ETF 实时行情{RESET}")
    print(f"  {_pad('代码', CODE_W)} {_pad('名称', NAME_W)} {_pad('最新价', PRICE_W, '>')} {_pad('涨跌幅', CHG_W, '>')}")
    print("  " + "─" * (2 + CODE_W + 1 + NAME_W + 1 + PRICE_W + 1 + CHG_W))

    gold_chg = 0.0
    for _, r in etfs.iterrows():
        code = str(r.get("代码", ""))
        if code in gold_etfs:
            price = str(r.get("最新价", "-"))
            chg = _safe_float(r.get("涨跌幅", 0))
            chg_str = _color_chg(chg)
            print(f"  {_pad(code, CODE_W)} {_pad(_trunc(gold_etfs[code], NAME_W), NAME_W)} {_pad(price, PRICE_W, '>')} {_pad(chg_str, CHG_W, '>')}")
            if code == "518880":
                gold_chg = chg
    print()
    return gold_chg


def show_portfolio_etfs(etfs: pd.DataFrame, lofs: pd.DataFrame | None = None) -> dict[str, float]:
    """ETFs corresponding to feeder funds in portfolio. Returns category changes."""
    # Categorized by asset class. Codes in "lof" set are looked up in LOF data.
    CATEGORIES: dict[str, dict[str, str]] = {
        "🥇 黄金": {
            "518880": "华安黄金ETF",
            "518800": "国泰黄金ETF",
        },
        "🥈 白银": {
            "161226": "白银LOF",
        },
        "📈 A股大盘": {
            "510300": "沪深300ETF",
            "510050": "上证50ETF",
        },
        "🔬 科技/半导体": {
            "588000": "科创50ETF",
            "159994": "5G通信ETF",
        },
        "🌍 海外": {
            "159941": "纳指ETF",
            "513100": "纳指100ETF",
        },
    }

    LOF_CODES = {"161226"}  # codes to look up in LOF data

    CODE_W, NAME_W, PRICE_W, CHG_W = 8, 22, 10, 10

    print(f"  {BOLD}🔗 持仓关联 ETF（按品类）{RESET}")

    cat_changes: dict[str, float] = {}

    for cat_label, etf_dict in CATEGORIES.items():
        print(f"\n  {BOLD}{cat_label}{RESET}")
        print(f"  {_pad('代码', CODE_W)} {_pad('名称', NAME_W)} {_pad('最新价', PRICE_W, '>')} {_pad('涨跌幅', CHG_W, '>')}")
        print("  " + "─" * (2 + CODE_W + 1 + NAME_W + 1 + PRICE_W + 1 + CHG_W))

        cat_chg_sum = 0.0
        cat_count = 0

        # Collect rows from both ETF and LOF data
        all_rows: list[tuple[str, str, float]] = []  # (code, price_str, chg)

        for _, r in etfs.iterrows():
            code = str(r.get("代码", ""))
            if code in etf_dict and code not in LOF_CODES:
                price_raw = r.get("最新价", "-")
                price_str = str(price_raw) if pd.notna(price_raw) else "-"
                chg = _safe_float(r.get("涨跌幅", 0))
                all_rows.append((code, price_str, chg))

        # Also check LOF data for codes like 161226
        if lofs is not None:
            for _, r in lofs.iterrows():
                code = str(r.get("代码", ""))
                if code in etf_dict and code in LOF_CODES:
                    price_raw = r.get("最新价", "-")
                    price_str = str(price_raw) if pd.notna(price_raw) else "-"
                    chg = _safe_float(r.get("涨跌幅", 0))
                    all_rows.append((code, price_str, chg))

        for code, price_str, chg in all_rows:
            chg_str = _color_chg(chg)
            name = etf_dict[code]
            print(f"  {_pad(code, CODE_W)} {_pad(_trunc(name, NAME_W), NAME_W)} {_pad(price_str, PRICE_W, '>')} {_pad(chg_str, CHG_W, '>')}")
            cat_chg_sum += chg
            cat_count += 1

        if cat_count > 0:
            cat_changes[cat_label] = cat_chg_sum / cat_count

    print()
    return cat_changes


def show_comprehensive_summary(
    index_changes: dict[str, float],
    gold_chg: float,
    cat_changes: dict[str, float],
    top_inds: list[tuple[str, float]],
    bottom_inds: list[tuple[str, float]],
) -> None:
    """Comprehensive market summary covering all asset classes."""

    # ── 大盘 ──
    sh_chg = index_changes.get("上证指数", 0)
    hs300_chg = index_changes.get("沪深300", 0)
    zz500_chg = index_changes.get("中证500", 0)
    zz1000_chg = index_changes.get("中证1000", 0)
    kc50_chg = index_changes.get("科创50", 0)
    kc_chip_chg = index_changes.get("科创芯片", 0)

    # ── 品类 ──
    gold_avg = cat_changes.get("🥇 黄金", gold_chg)
    silver_avg = cat_changes.get("🥈 白银", 0)
    a_share_avg = cat_changes.get("📈 A股大盘", hs300_chg)
    tech_avg = cat_changes.get("🔬 科技/半导体", kc_chip_chg)
    overseas_avg = cat_changes.get("🌍 海外", 0)

    print(f"  {BOLD}📝 市场综合点评{RESET}\n")

    # 1. 大盘定调
    print(f"  {BOLD}── 大盘 ──{RESET}")
    # Determine market tone
    if sh_chg > 0.5:
        tone = f"{GREEN}强势上涨{RESET}"
    elif sh_chg > 0.1:
        tone = f"{GREEN}小幅上涨{RESET}"
    elif sh_chg > -0.1:
        tone = f"{YELLOW}窄幅横盘{RESET}"
    elif sh_chg > -0.5:
        tone = f"{RED}小幅下跌{RESET}"
    else:
        tone = f"{RED}明显下跌{RESET}"

    # Style rotation analysis
    large_vs_small = hs300_chg - zz1000_chg if zz1000_chg != 0 else 0
    if large_vs_small > 0.3:
        style = f"大票强于小票（沪深300 {_color_chg_short(hs300_chg)} vs 中证1000 {_color_chg_short(zz1000_chg)}）"
    elif large_vs_small < -0.3:
        style = f"小票强于大票（中证1000 {_color_chg_short(zz1000_chg)} vs 沪深300 {_color_chg_short(hs300_chg)}）"
    else:
        style = f"大小票同步（沪深300 {_color_chg_short(hs300_chg)}，中证1000 {_color_chg_short(zz1000_chg)}）"

    print(f"  上证指数 {_color_chg_short(sh_chg)} → 市场{_sign(sh_chg)} {tone}")
    print(f"  {style}")
    print(f"  科创50 {_color_chg_short(kc50_chg)} | 科创芯片 {_color_chg_short(kc_chip_chg)}")

    # 2. 行业轮动
    print(f"\n  {BOLD}── 行业轮动 ──{RESET}")
    if top_inds:
        top_names = [n for n, _ in top_inds[:3]]
        print(f"  领涨: {GREEN}{'、'.join(top_names)}{RESET}")
    if bottom_inds:
        bottom_names = [n for n, _ in bottom_inds[:3]]
        print(f"  领跌: {RED}{'、'.join(bottom_names)}{RESET}")
    if not top_inds and not bottom_inds:
        print(f"  {DIM}（行业板块数据未获取到）{RESET}")

    # 3. 各品类表现
    print(f"\n  {BOLD}── 持仓品类 ──{RESET}")
    cat_lines = []
    if gold_avg != 0 or gold_chg != 0:
        cat_lines.append(f"🥇 黄金 {_color_chg_short(gold_avg if gold_avg else gold_chg)}")
    if abs(silver_avg) > 0.001:
        cat_lines.append(f"🥈 白银 {_color_chg_short(silver_avg)}")
    if a_share_avg != 0:
        cat_lines.append(f"📈 A股大盘 {_color_chg_short(a_share_avg)}")
    if abs(tech_avg) > 0.001:
        cat_lines.append(f"🔬 科技/半导体 {_color_chg_short(tech_avg)}")
    if abs(overseas_avg) > 0.001:
        cat_lines.append(f"🌍 海外 {_color_chg_short(overseas_avg)}")
    if cat_lines:
        print(f"  {' | '.join(cat_lines)}")
    else:
        print(f"  {DIM}（持仓关联 ETF 数据未获取到）{RESET}")

    # 4. 市场温度（基于指数涨跌和行业分布）
    print(f"\n  {BOLD}── 市场温度 ──{RESET}")
    # Count how many major indices are positive
    idx_vals = [sh_chg, hs300_chg, zz500_chg, zz1000_chg, kc50_chg]
    pos_count = sum(1 for v in idx_vals if v > 0.05)
    neg_count = sum(1 for v in idx_vals if v < -0.05)
    total = len(idx_vals)

    if pos_count >= 4:
        temp = f"{GREEN}🔥 普涨{RESET}（{pos_count}/{total} 指数上涨）"
    elif pos_count >= 3:
        temp = f"{GREEN}偏暖{RESET}（{pos_count}/{total} 指数上涨）"
    elif neg_count >= 4:
        temp = f"{RED}❄️ 普跌{RESET}（{neg_count}/{total} 指数下跌）"
    elif neg_count >= 3:
        temp = f"{RED}偏冷{RESET}（{neg_count}/{total} 指数下跌）"
    else:
        temp = f"{YELLOW}分化{RESET}（涨跌互现）"
    print(f"  {temp}")

    # 5. 操作参考
    print(f"\n  {BOLD}💡 操作参考{RESET}")

    suggestions: list[str] = []

    # Gold
    if gold_avg > 1.0:
        suggestions.append(f"黄金 ETF 大涨 {_color_chg_short(gold_avg)}，持有但不宜追高")
    elif gold_avg > 0.3:
        suggestions.append(f"黄金 ETF 温和上涨，现有仓位持有")
    elif gold_avg < -1.0:
        suggestions.append(f"黄金 ETF 大跌 {_color_chg_short(gold_avg)}，关注支撑位，可考虑分批加仓")
    elif gold_avg < -0.3:
        suggestions.append(f"黄金 ETF 回调，观望是否企稳")

    # A-share broad
    if sh_chg < -1.0:
        suggestions.append(f"大盘跌幅较大（{_color_chg_short(sh_chg)}），定投可适当加大金额")
    elif abs(sh_chg) < 0.15:
        suggestions.append(f"大盘横盘，定投按原计划执行")

    # Tech/semiconductor
    if abs(kc_chip_chg) > 2.0:
        suggestions.append(f"半导体波动较大（{_color_chg_short(kc_chip_chg)}），519674 仓位小无需恐慌")

    # Sector rotation hint
    if top_inds and sh_chg > 0.2:
        suggestions.append(f"今日热点: {GREEN}{top_inds[0][0]}{RESET}，关注持续性")

    # Overseas — check if data available
    if abs(overseas_avg) > 0.001:
        if overseas_avg > 0.5:
            suggestions.append(f"海外（纳指）走强 {_color_chg_short(overseas_avg)}，QDII 仓位持有")
        elif overseas_avg < -1.0:
            suggestions.append(f"海外（纳指）回调 {_color_chg_short(overseas_avg)}，关注是否加仓机会")

    for s in suggestions:
        print(f"  • {s}")

    print()


def show_brief_summary(
    index_changes: dict[str, float],
    gold_chg: float,
    cat_changes: dict[str, float],
    top_inds: list[tuple[str, float]],
    bottom_inds: list[tuple[str, float]],
) -> None:
    """Condensed one-section summary for --brief mode."""
    sh_chg = index_changes.get("上证指数", 0)
    kc50_chg = index_changes.get("科创50", 0)
    kc_chip_chg = index_changes.get("科创芯片", 0)
    overseas_avg = cat_changes.get("🌍 海外", 0)
    tech_avg = cat_changes.get("🔬 科技/半导体", kc_chip_chg)

    print(f"\n  {BOLD}📝 一句话总结{RESET}")
    parts = []

    # Market
    if sh_chg > 0.3:
        parts.append(f"大盘{_color_chg_short(sh_chg)} 偏强")
    elif sh_chg < -0.3:
        parts.append(f"大盘{_color_chg_short(sh_chg)} 偏弱")
    else:
        parts.append(f"大盘{_color_chg_short(sh_chg)} 横盘")

    # Categories from portfolio
    for cat_label in ["🥇 黄金", "📈 A股大盘", "🔬 科技/半导体", "🌍 海外"]:
        val = cat_changes.get(cat_label, 0)
        if abs(val) > 0.05:
            emoji = cat_label.split()[0]
            parts.append(f"{emoji}{_color_chg_short(val)}")

    # Top/bottom sectors
    if top_inds:
        parts.append(f"领涨:{GREEN}{top_inds[0][0]}{RESET}")
    if bottom_inds:
        parts.append(f"领跌:{RED}{bottom_inds[0][0]}{RESET}")

    print(f"  {' | '.join(parts)}")

    # Quick hints
    print(f"\n  {BOLD}💡 操作参考{RESET}")
    hints = []
    if sh_chg < -1.0:
        hints.append(f"大盘跌幅较大，定投可适当加大金额")
    if abs(kc50_chg) > 3.0:
        hints.append(f"科创50 波动较大（{_color_chg_short(kc50_chg)}），519674 仓位小无需恐慌")
    if abs(gold_chg) > 1.0:
        direction = "大涨" if gold_chg > 0 else "大跌"
        hints.append(f"黄金 {direction}，不宜追涨杀跌")
    if overseas_avg < -1.0:
        hints.append(f"纳指回调 {_color_chg_short(overseas_avg)}，关注加仓机会")
    if not hints:
        hints.append(f"市场波动正常，按计划执行定投")
    for h in hints:
        print(f"  • {h}")
    print()


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="实时行情快照")
    parser.add_argument("--brief", action="store_true", help="简洁模式")
    parser.add_argument("--gold", action="store_true", help="只看黄金")
    parser.add_argument("--no-sector", action="store_true", help="跳过行业/概念板块（加速）")
    args = parser.parse_args()

    print()
    print(f"  ╔{'═' * 56}╗")
    print(f"  ║                    📡 实时行情快照                     ║")
    print(f"  ╚{'═' * 56}╝")

    # ── Fetch ETF data ──
    try:
        etfs = _fetch_etfs()
    except Exception as e:
        print(f"  [ERROR] 获取 ETF 数据失败: {e}")
        return

    # ── Gold-only mode ──
    if args.gold:
        gold_chg = show_gold(etfs)
        return

    # Rate-limit between requests
    time.sleep(1.0)

    # ── Fetch LOF data (for 白银LOF etc) ──
    lofs = _fetch_lofs()
    if lofs is not None:
        time.sleep(1.0)

    # ── Fetch index data ──
    try:
        indices = _fetch_indices()
    except Exception as e:
        print(f"  [ERROR] 获取指数数据失败: {e}")
        return

    # ── Fetch sector data (optional) ──
    industries = None
    concepts = None
    if not args.no_sector:
        time.sleep(1.0)
        industries = _fetch_industry_sectors()
        if industries is not None:
            time.sleep(1.0)
            concepts = _fetch_concept_sectors()

    # ── Display sections ──
    index_changes = show_broad_indices(indices)

    top_inds: list[tuple[str, float]] = []
    bottom_inds: list[tuple[str, float]] = []
    if not args.no_sector:
        top_inds, bottom_inds = show_sector_leaders(industries, concepts)

    gold_chg = show_gold(etfs)
    cat_changes = show_portfolio_etfs(etfs, lofs)

    if args.brief:
        show_brief_summary(index_changes, gold_chg, cat_changes, top_inds, bottom_inds)
    else:
        show_comprehensive_summary(index_changes, gold_chg, cat_changes, top_inds, bottom_inds)


if __name__ == "__main__":
    main()
