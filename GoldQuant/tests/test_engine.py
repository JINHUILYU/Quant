from __future__ import annotations

import pandas as pd
import numpy as np

from goldquant.config import GoldQuantConfig
from goldquant.backtest.engine import BacktestEngine
from goldquant.backtest.metrics import compute_metrics, BacktestResult
from goldquant.strategies.examples import MovingAverageCrossover


def make_flat_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=50, freq="B")
    return pd.DataFrame({
        "date": dates,
        "open": [100.0] * 50,
        "close": [100.0] * 50,
        "high": [100.0] * 50,
        "low": [100.0] * 50,
    })


def make_uptrend_data() -> pd.DataFrame:
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    # Uptrend with oscillations so MA crossover can happen
    close = []
    price = 100.0
    for i in range(n):
        if i % 20 < 10:
            price += 2.0
        else:
            price -= 0.5
        close.append(price)
    close_arr = np.array(close)
    return pd.DataFrame({
        "date": dates,
        "open": close_arr - 1,
        "close": close_arr,
        "high": close_arr + 1,
        "low": close_arr - 1,
    })


def test_zero_trades_on_flat_data():
    """Flat price should produce no trades for crossover strategies."""
    cfg = GoldQuantConfig()
    engine = BacktestEngine(cfg)
    # Use very short windows so SMAs exist
    s = MovingAverageCrossover(short_window=5, long_window=10)
    raw = engine.run(s, make_flat_data())
    assert len(raw["trades"]) == 0
    # Equity should stay at initial capital
    eq = raw["equity_curve"]["equity"].values
    assert abs(eq[-1] - cfg.initial_capital) < 0.01


def test_equity_curve_length():
    """Equity curve should have same length as input data."""
    engine = BacktestEngine()
    s = MovingAverageCrossover(short_window=5, long_window=10)
    df = make_flat_data()
    raw = engine.run(s, df)
    assert len(raw["equity_curve"]) == len(df)


def test_metrics_with_no_trades():
    """Metrics should handle zero-trade case gracefully."""
    engine = BacktestEngine()
    s = MovingAverageCrossover(short_window=5, long_window=10)
    raw = engine.run(s, make_flat_data())
    m = compute_metrics(raw)
    assert isinstance(m, BacktestResult)
    assert m.total_trades == 0
    assert m.win_rate_pct == 0.0


def test_metrics_with_trades():
    """Metrics should be computed correctly when trades exist."""
    engine = BacktestEngine()
    # Use very reactive MA crossover on uptrend data
    s = MovingAverageCrossover(short_window=2, long_window=5)
    raw = engine.run(s, make_uptrend_data())
    m = compute_metrics(raw)
    assert m.total_trades > 0
    assert m.total_return_pct != 0
    assert m.max_drawdown_pct >= 0
    # Sharpe should be finite
    assert np.isfinite(m.sharpe_ratio)


def test_trade_record_fields():
    """Trade records should have all expected fields."""
    engine = BacktestEngine()
    s = MovingAverageCrossover(short_window=2, long_window=5)
    raw = engine.run(s, make_uptrend_data())
    for t in raw["trades"]:
        assert t.entry_date is not None
        assert t.exit_date is not None
        assert t.entry_price > 0
        assert t.exit_price > 0
        assert t.bars_held >= 0
        assert t.exit_date >= t.entry_date


def test_commission_reduces_return():
    """With commission, return should be lower than without."""
    cfg_no_comm = GoldQuantConfig(commission_pct=0.0, slippage_pct=0.0)
    cfg_with_comm = GoldQuantConfig(commission_pct=0.01, slippage_pct=0.0)

    s = MovingAverageCrossover(short_window=2, long_window=5)
    df = make_uptrend_data()

    raw_no = BacktestEngine(cfg_no_comm).run(s, df)
    raw_with = BacktestEngine(cfg_with_comm).run(s, df)

    m_no = compute_metrics(raw_no)
    m_with = compute_metrics(raw_with)

    # With high commission, return should be lower (or equal if no trades)
    if m_no.total_trades > 0:
        assert m_with.total_return_pct <= m_no.total_return_pct
