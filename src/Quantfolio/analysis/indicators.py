from __future__ import annotations

import pandas as pd
import numpy as np


def add_sma(df: pd.DataFrame, window: int, col: str = "close") -> pd.DataFrame:
    df = df.copy()
    df[f"sma_{window}"] = df[col].rolling(window).mean()
    return df


def add_ema(df: pd.DataFrame, window: int, col: str = "close") -> pd.DataFrame:
    df = df.copy()
    df[f"ema_{window}"] = df[col].ewm(span=window, adjust=False).mean()
    return df


def add_rsi(df: pd.DataFrame, period: int = 14, col: str = "close") -> pd.DataFrame:
    df = df.copy()
    delta = df[col].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        df[f"rsi_{period}"] = 100.0 - (100.0 / (1.0 + rs))
    return df


def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    col: str = "close",
) -> pd.DataFrame:
    df = df.copy()
    ema_fast = df[col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[col].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


def add_bollinger(
    df: pd.DataFrame,
    period: int = 20,
    std: float = 2.0,
    col: str = "close",
) -> pd.DataFrame:
    df = df.copy()
    df["bb_middle"] = df[col].rolling(period).mean()
    bb_std = df[col].rolling(period).std()
    df["bb_upper"] = df["bb_middle"] + std * bb_std
    df["bb_lower"] = df["bb_middle"] - std * bb_std
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df[f"atr_{period}"] = tr.ewm(alpha=1 / period, adjust=False).mean()
    return df


def add_returns(df: pd.DataFrame, col: str = "close") -> pd.DataFrame:
    df = df.copy()
    df["ret"] = df[col].pct_change()
    df["log_ret"] = np.log(df[col] / df[col].shift(1))
    return df


def add_all(
    df: pd.DataFrame,
    config=None,
    col: str = "close",
) -> pd.DataFrame:
    """Apply all standard indicators at once."""
    if config is None:
        from Quantfolio.config import QuantfolioConfig
        config = QuantfolioConfig()
    df = add_sma(df, config.sma_short, col)
    df = add_sma(df, config.sma_long, col)
    df = add_ema(df, config.sma_short, col)
    df = add_ema(df, config.sma_long, col)
    df = add_rsi(df, config.rsi_period, col)
    df = add_macd(df, config.macd_fast, config.macd_slow, config.macd_signal, col)
    df = add_bollinger(df, config.bollinger_period, config.bollinger_std, col)
    df = add_atr(df, config.atr_period)
    df = add_returns(df, col)
    return df
