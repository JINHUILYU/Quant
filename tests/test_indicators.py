from __future__ import annotations

import pandas as pd
import numpy as np

from Quantfolio.analysis.indicators import (
    add_sma, add_ema, add_rsi, add_macd, add_bollinger, add_atr,
)


def make_ohlc() -> pd.DataFrame:
    return pd.DataFrame({
        "close": [10, 12, 14, 13, 15, 14, 16, 18, 17, 20],
        "high":  [10, 13, 15, 14, 16, 15, 17, 19, 18, 21],
        "low":   [9,  11, 13, 12, 14, 13, 15, 17, 16, 19],
    })


def test_sma():
    df = add_sma(make_ohlc(), 3)
    assert abs(df["sma_3"].iloc[2] - 12.0) < 0.01  # (10+12+14)/3
    assert pd.isna(df["sma_3"].iloc[0])
    assert pd.isna(df["sma_3"].iloc[1])


def test_ema():
    df = add_ema(make_ohlc(), 3)
    assert not pd.isna(df["ema_3"].iloc[0])  # EMA starts immediately
    assert df["ema_3"].iloc[0] == 10.0  # First EMA = first close


def test_rsi_bounds():
    """RSI should be between 0 and 100."""
    df = add_rsi(make_ohlc(), 5)
    valid = df["rsi_5"].dropna()
    assert len(valid) > 0
    assert valid.min() >= 0
    assert valid.max() <= 100


def test_rsi_extreme():
    """A pure uptrend should produce very high RSI."""
    df = pd.DataFrame({"close": list(range(1, 51))})  # 50 bars going up
    df = add_rsi(df, 14)
    # In a pure uptrend with no down days, RSI = 100 (no losses)
    # The last valid RSI value should be very close to 100
    final = df["rsi_14"].iloc[-1]
    assert not pd.isna(final), f"Expected non-NaN RSI, got {final}"
    assert final > 95, f"Expected RSI > 95, got {final}"


def test_macd_columns():
    df = add_macd(make_ohlc())
    assert "macd" in df.columns
    assert "macd_signal" in df.columns
    assert "macd_hist" in df.columns
    # macd_hist = macd - signal
    diff = (df["macd"] - df["macd_signal"] - df["macd_hist"]).dropna().abs().max()
    assert diff < 1e-9


def test_bollinger_bands():
    df = add_bollinger(make_ohlc(), 5, 2.0)
    valid = df["bb_middle"].notna()
    assert (df.loc[valid, "bb_upper"] >= df.loc[valid, "bb_middle"]).all()
    assert (df.loc[valid, "bb_middle"] >= df.loc[valid, "bb_lower"]).all()

    # On a flat series, upper == middle == lower
    flat = pd.DataFrame({"close": [10] * 20})
    flat = add_bollinger(flat, 5, 2.0)
    v = flat.dropna()
    assert (v["bb_upper"] == v["bb_middle"]).all()
    assert (v["bb_lower"] == v["bb_middle"]).all()


def test_atr_positive():
    df = add_atr(make_ohlc(), 5)
    valid = df["atr_5"].dropna()
    assert (valid > 0).all()


def test_indicators_do_not_mutate_input():
    df = make_ohlc()
    orig_cols = df.columns.tolist()
    result = add_sma(df, 3)
    assert df.columns.tolist() == orig_cols  # Input unchanged
    assert "sma_3" in result.columns  # Output has new column
