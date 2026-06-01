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

    # 优先使用东方财富（数据更全），失败则降级到新浪
    try:
        return _retry(lambda: _with_browser_headers(ak.stock_zh_index_spot_em), "指数数据(EM)")
    except Exception:
        print(f"  [INFO] 东方财富指数接口不可用，切换新浪数据源...")
        return _retry(lambda: ak.stock_zh_index_spot_sina(), "指数数据(Sina)")


def _fetch_etfs() -> pd.DataFrame:
    import akshare as ak

    return _retry(lambda: ak.fund_etf_spot_em(), "ETF 数据")


# ── Display helpers ──────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


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
    pad = max(0, width - d)
    if align == ">":
        return " " * pad + s
    return s + " " * pad


def _trunc(s: str, width: int) -> str:
    """Truncate to display width."""
    import re
    import unicodedata
    clean = re.sub(r"\033\[[0-9;]*m", "", s)
    w = 0
    result: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        # skip ANSI sequences
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
    """Colored change string. Color applied last, after padding."""
    if val > 0:
        return f"{GREEN}{val:+.2f}%{RESET}"
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
    CODE_W, NAME_W, PRICE_W, CHG_W = 8, 32, 10, 10

    print(f"\n  {BOLD}🥇 黄金 ETF 实时行情{RESET}")
    print(f"  {_pad('代码', CODE_W)} {_pad('名称', NAME_W)} {_pad('最新价', PRICE_W, '>')} {_pad('涨跌幅', CHG_W, '>')}")
    print("  " + "─" * (2 + CODE_W + 1 + NAME_W + 1 + PRICE_W + 1 + CHG_W))
    for _, r in etfs.iterrows():
        code = str(r.get("代码", ""))
        if code in gold_etfs:
            price = str(r.get("最新价", "-"))
            chg = r.get("涨跌幅", 0)
            try:
                chg_f = float(chg) if chg and chg != "-" else 0.0
            except (ValueError, TypeError):
                chg_f = 0.0
            chg_str = f"{chg_f:+.2f}%" if chg_f != 0 else " 0.00%"
            print(f"  {_pad(code, CODE_W)} {_pad(_trunc(gold_etfs[code], NAME_W), NAME_W)} {_pad(price, PRICE_W, '>')} {_pad(chg_str, CHG_W, '>')}")
    print()


def show_key_indices(indices: pd.DataFrame) -> None:
    """Filter to indices relevant to portfolio."""
    KEYWORDS = [
        "上证指数", "沪深300", "上证50", "科创50", "科创芯片",
        "创业板指", "深证成指", "上证综合全收益",
    ]
    NAME_W, PRICE_W, CHG_W = 16, 10, 10

    print(f"  {BOLD}📊 关键指数{RESET}")
    print(f"  {_pad('名称', NAME_W)} {_pad('最新', PRICE_W, '>')} {_pad('涨跌幅', CHG_W, '>')}")
    print("  " + "─" * (2 + NAME_W + 1 + PRICE_W + 1 + CHG_W))
    shown = set()
    for _, r in indices.iterrows():
        name = str(r.get("名称", ""))
        for kw in KEYWORDS:
            if kw in name and name not in shown:
                shown.add(name)
                price = str(r.get("最新价", "-"))
                chg_raw = r.get("涨跌幅", 0)
                try:
                    chg = float(chg_raw) if chg_raw else 0.0
                except (ValueError, TypeError):
                    chg = 0.0
                chg_str = f"{chg:+.2f}%" if chg != 0 else " 0.00%"
                print(f"  {_pad(name, NAME_W)} {_pad(price, PRICE_W, '>')} {_pad(chg_str, CHG_W, '>')}")
                break
    print()


def show_portfolio_etfs(etfs: pd.DataFrame) -> None:
    """ETFs corresponding to feeder funds in portfolio."""
    RELEVANT = {
        "159941": "纳指ETF（→019548/016452联接）",
        "513100": "纳指100ETF（→016452联接）",
        "510300": "沪深300ETF（→110020联接）",
        "510050": "上证50ETF（→006220联接）",
        "588000": "科创50ETF（→半导体相关）",
        "159994": "5G通信ETF",
        "161226": "白银LOF（→161226）",
    }
    CODE_W, NAME_W, PRICE_W, CHG_W = 8, 34, 10, 10

    print(f"  {BOLD}🔗 持仓关联 ETF{RESET}")
    print(f"  {_pad('代码', CODE_W)} {_pad('名称', NAME_W)} {_pad('最新价', PRICE_W, '>')} {_pad('涨跌幅', CHG_W, '>')}")
    print("  " + "─" * (2 + CODE_W + 1 + NAME_W + 1 + PRICE_W + 1 + CHG_W))
    for _, r in etfs.iterrows():
        code = str(r.get("代码", ""))
        if code in RELEVANT:
            price_raw = r.get("最新价", "-")
            price_str = str(price_raw) if pd.notna(price_raw) else "-"
            chg = r.get("涨跌幅", 0)
            try:
                chg_f = float(chg) if pd.notna(chg) and chg != "-" else 0.0
            except (ValueError, TypeError):
                chg_f = 0.0
            chg_str = f"{chg_f:+.2f}%" if chg_f != 0 else " 0.00%"
            print(f"  {_pad(code, CODE_W)} {_pad(_trunc(RELEVANT[code], NAME_W), NAME_W)} {_pad(price_str, PRICE_W, '>')} {_pad(chg_str, CHG_W, '>')}")
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
        parts.append(f"大盘{_color_chg(sh_chg)} 偏强")
    elif sh_chg < -0.3:
        parts.append(f"大盘{_color_chg(sh_chg)} 偏弱")
    else:
        parts.append(f"大盘{_color_chg(sh_chg)} 横盘")

    if gold_chg > 0.1:
        parts.append(f"黄金{_color_chg(gold_chg)}")
    elif gold_chg < -0.1:
        parts.append(f"黄金{_color_chg(gold_chg)}")
    else:
        parts.append("黄金横盘")

    if chip_chg < -1:
        parts.append(f"半导体{_color_chg(chip_chg)} 承压")
    elif chip_chg > 1:
        parts.append(f"半导体{_color_chg(chip_chg)} 强势")

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
        print(f"  半导体波动较大（{_color_chg(chip_chg)}），519674 仓位小，无需恐慌")
    print()


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="实时行情快照")
    parser.add_argument("--brief", action="store_true", help="简洁模式")
    parser.add_argument("--gold", action="store_true", help="只看黄金")
    args = parser.parse_args()

    print()
    print(f"  ╔{'═' * 52}╗")
    print(f"  ║                  📡 实时行情快照                   ║")
    print(f"  ╚{'═' * 52}╝")

    try:
        etfs = _fetch_etfs()
    except Exception as e:
        print(f"  [ERROR] 获取 ETF 数据失败: {e}")
        return

    if args.gold:
        show_gold(etfs)
        return

    # 两次请求之间稍作间隔，避免触发限流
    time.sleep(1.5)

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
