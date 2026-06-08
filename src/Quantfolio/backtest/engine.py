from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import numpy as np

from Quantfolio.config import QuantfolioConfig
from Quantfolio.strategies.base import Strategy


@dataclass
class TradeRecord:
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp
    exit_price: float
    direction: int  # 1 = long
    pnl: float
    pnl_pct: float
    bars_held: int


class BacktestEngine:
    """Bar-by-bar simulation engine for long-only strategies."""

    def __init__(self, config: QuantfolioConfig | None = None):
        self.cfg = config or QuantfolioConfig()

    def run(self, strategy: Strategy, data: pd.DataFrame) -> dict[str, Any]:
        data = strategy.init(data.copy())
        n = len(data)

        context: dict[str, Any] = {"position": 0, "entry_price": 0.0, "entry_idx": 0}
        trades: list[TradeRecord] = []
        equity = np.full(n, np.nan)
        cash = self.cfg.initial_capital
        units = 0
        entry_price = 0.0
        entry_idx = 0

        for i in range(n):
            row = data.iloc[i]
            price = float(row["close"])

            if i == 0 and pd.isna(price):
                equity[i] = cash
                continue

            signal = strategy.next(i, row, context)

            # Execute exit
            if signal == -1 and units > 0:
                exit_price = price * (1 - self.cfg.slippage_pct)
                pnl_per_unit = exit_price - entry_price
                gross_pnl = pnl_per_unit * units
                commission = entry_price * units * self.cfg.commission_pct + exit_price * units * self.cfg.commission_pct
                net_pnl = gross_pnl - commission
                cash += entry_price * units + net_pnl
                trades.append(TradeRecord(
                    entry_date=data.iloc[entry_idx]["date"],
                    entry_price=entry_price,
                    exit_date=row["date"],
                    exit_price=exit_price,
                    direction=1,
                    pnl=net_pnl,
                    pnl_pct=(pnl_per_unit / entry_price * 100) if entry_price else 0,
                    bars_held=i - entry_idx,
                ))
                units = 0
                entry_price = 0.0
                context["position"] = 0

            # Execute entry
            if signal == 1 and units == 0:
                entry_price = price * (1 + self.cfg.slippage_pct)
                units = cash / entry_price
                cash = 0.0
                entry_idx = i
                context["position"] = 1

            # Mark-to-market equity
            if units > 0:
                equity[i] = units * price * (1 - self.cfg.slippage_pct)
            else:
                equity[i] = cash

        return {
            "equity_curve": pd.DataFrame({
                "date": data["date"],
                "equity": equity,
            }),
            "trades": trades,
            "strategy": strategy.name,
            "symbol": self.cfg.default_symbol,
            "initial_capital": self.cfg.initial_capital,
        }
