from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Transaction:
    date: pd.Timestamp
    product: str
    type: str          # "buy" | "sell"
    amount: float       # net cash flow (buy: total paid incl. fee; sell: net received after fee)
    price: float        # NAV per share
    shares: float       # number of shares
    fee: float          # transaction fee in CNY
    notes: str = ""


@dataclass
class Holding:
    product: str
    total_shares: float
    avg_cost: float            # weighted-average cost per share
    current_price: float        # latest NAV
    market_value: float         # total_shares * current_price
    cost_basis: float           # allocated cost of remaining shares
    unrealized_pnl: float       # market_value - cost_basis
    unrealized_pnl_pct: float   # (current_price / avg_cost - 1) * 100


@dataclass
class PortfolioSummary:
    product: str
    holdings: list[Holding]
    transactions: list[Transaction]
    daily_value: pd.DataFrame
    nav_history: pd.DataFrame

    total_invested: float        # sum of (buy_amount + buy_fee)
    total_withdrawn: float       # sum of (sell_amount - sell_fee)
    net_cash_flow: float         # total_withdrawn - total_invested
    current_value: float         # latest portfolio market value
    total_pnl: float             # current_value + total_withdrawn - total_invested
    total_pnl_pct: float         # total_pnl / total_invested * 100

    max_drawdown_pct: float
    irr_annual_pct: float
    total_buys: int
    total_sells: int
    start_date: str
    end_date: str

    def summary(self) -> str:
        sep = "─" * 55
        lines = [sep]
        lines.append(f"  持仓分析报告 — {self.product}")
        lines.append(sep)
        lines.append(f"  数据区间: {self.start_date} ~ {self.end_date}")
        lines.append("")
        lines.append("  [交易统计]")
        lines.append(f"  买入次数: {self.total_buys}    卖出次数: {self.total_sells}")
        lines.append(f"  累计投入: ¥{self.total_invested:,.2f}")
        lines.append(f"  累计取出: ¥{self.total_withdrawn:,.2f}")
        lines.append("")

        if self.holdings:
            h = self.holdings[0]
            lines.append("  [当前持仓]")
            lines.append(f"  持有份额: {h.total_shares:,.2f}")
            lines.append(f"  平均成本: ¥{h.avg_cost:,.4f}")
            lines.append(f"  当前净值: ¥{h.current_price:,.4f}")
            lines.append(f"  持仓市值: ¥{h.market_value:,.2f}")
            lines.append(f"  持仓成本: ¥{h.cost_basis:,.2f}")
            lines.append(f"  浮动盈亏: ¥{h.unrealized_pnl:+,.2f}  ({h.unrealized_pnl_pct:+.2f}%)")
            lines.append("")

        lines.append("  [业绩指标]")
        lines.append(f"  总盈亏:    ¥{self.total_pnl:+,.2f}")
        lines.append(f"  总收益率:  {self.total_pnl_pct:+.2f}%")
        lines.append(f"  年化 IRR:  {self.irr_annual_pct:+.2f}%")
        lines.append(f"  最大回撤:  {self.max_drawdown_pct:.2f}%")
        lines.append(sep)
        return "\n".join(lines)
