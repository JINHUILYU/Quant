from __future__ import annotations

import pandas as pd

from Quantfolio.strategies.base import Strategy
from Quantfolio.strategies.examples import (
    MovingAverageCrossover, RSIStrategy, BollingerBreakout,
)


def make_trend_data() -> pd.DataFrame:
    """Simple uptrend with a dip in the middle."""
    closes = [10, 11, 12, 13, 12, 11, 10, 11, 12, 13, 14, 15]
    return pd.DataFrame({"close": closes})


def test_registry():
    assert "MovingAverageCrossover" in Strategy.registry
    assert "RSIStrategy" in Strategy.registry
    assert "BollingerBreakout" in Strategy.registry


def test_ma_crossover_init():
    s = MovingAverageCrossover(short_window=5, long_window=20)
    df = make_trend_data()
    df = s.init(df)
    assert "sma_5" in df.columns
    assert "sma_20" in df.columns


def test_ma_crossover_no_signal_before_indicators():
    """Should return 0 when SMA values are NaN."""
    s = MovingAverageCrossover(short_window=500, long_window=1000)
    df = make_trend_data()
    df = s.init(df)
    ctx = {}
    for i in range(len(df)):
        sig = s.next(i, df.iloc[i], ctx)
        assert sig == 0


def test_ma_crossover_buy_on_first_cross():
    """When short crosses above long, signal should be 1."""
    s = MovingAverageCrossover(short_window=2, long_window=3)
    df = make_trend_data()
    df = s.init(df)
    ctx = {"position": 0}
    signals = [s.next(i, df.iloc[i], ctx) for i in range(len(df))]
    # There should be at least one buy signal
    assert 1 in signals


def test_rsi_strategy_buys_when_oversold():
    """RSI strategy should buy when RSI is below oversold level."""
    s = RSIStrategy(period=3, oversold=30, overbought=70)
    # Create data with a sharp drop (which produces low RSI)
    df = pd.DataFrame({"close": [100, 101, 102, 103, 50, 48, 49, 50, 100, 101]})
    df = s.init(df)
    ctx = {"position": 0}
    signals = [s.next(i, df.iloc[i], ctx) for i in range(len(df))]
    assert 1 in signals


def test_rsi_strategy_sells_when_overbought():
    s = RSIStrategy(period=3, oversold=30, overbought=70)
    # Create data with a sharp rise
    df = pd.DataFrame({"close": [100, 102, 104, 106, 108, 110, 112, 114, 116, 118]})
    df = s.init(df)
    ctx = {"position": 1}  # Already in position
    signals = [s.next(i, df.iloc[i], ctx) for i in range(len(df))]
    # After some bars of uptrend, should get sell signal
    signal_values = [s for s in signals if s != 0]
    assert -1 in signal_values


def test_bollinger_strategy_columns():
    s = BollingerBreakout(period=5, std=2.0)
    df = make_trend_data()
    df = s.init(df)
    assert "bb_upper" in df.columns
    assert "bb_middle" in df.columns
    assert "bb_lower" in df.columns
