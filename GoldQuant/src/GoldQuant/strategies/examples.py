from __future__ import annotations

from typing import Any

import pandas as pd

from goldquant.config import GoldQuantConfig
from goldquant.strategies.base import Strategy
from goldquant.analysis.indicators import add_sma, add_rsi, add_bollinger
from goldquant.analysis.signals import SignalEvaluator


class MovingAverageCrossover(Strategy):
    """Buy when short SMA crosses above long SMA, sell when it crosses below."""

    def __init__(self, short_window: int = 5, long_window: int = 20, config=None):
        super().__init__(config)
        self.short_window = short_window
        self.long_window = long_window

    def init(self, data: pd.DataFrame) -> pd.DataFrame:
        data = add_sma(data, self.short_window)
        data = add_sma(data, self.long_window)
        return data

    def next(self, i: int, row: pd.Series, context: dict[str, Any]) -> int:
        sma_s = row.get(f"sma_{self.short_window}")
        sma_l = row.get(f"sma_{self.long_window}")
        if pd.isna(sma_s) or pd.isna(sma_l):
            return 0

        prev = context.setdefault("_prev_above", None)
        above = sma_s > sma_l

        signal = 0
        if prev is not None:
            if not prev and above:
                signal = 1
            elif prev and not above:
                signal = -1

        context["_prev_above"] = above
        return signal


class RSIStrategy(Strategy):
    """Buy when RSI crosses above oversold, sell when RSI crosses above overbought."""

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        config=None,
    ):
        super().__init__(config)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def init(self, data: pd.DataFrame) -> pd.DataFrame:
        return add_rsi(data, self.period)

    def next(self, i: int, row: pd.Series, context: dict[str, Any]) -> int:
        rsi = row.get(f"rsi_{self.period}")
        if pd.isna(rsi):
            return 0

        position = context.get("position", 0)

        if position == 0 and rsi < self.oversold:
            return 1
        if position == 1 and rsi > self.overbought:
            return -1
        return 0


class BollingerBreakout(Strategy):
    """Buy when close breaks above upper band, sell when close drops below middle."""

    def __init__(self, period: int = 20, std: float = 2.0, config=None):
        super().__init__(config)
        self.period = period
        self.std = std

    def init(self, data: pd.DataFrame) -> pd.DataFrame:
        return add_bollinger(data, self.period, self.std)

    def next(self, i: int, row: pd.Series, context: dict[str, Any]) -> int:
        close = row.get("close")
        upper = row.get("bb_upper")
        middle = row.get("bb_middle")
        if pd.isna(upper) or pd.isna(middle):
            return 0

        position = context.get("position", 0)

        if position == 0 and close > upper:
            return 1
        if position == 1 and close < middle:
            return -1
        return 0
