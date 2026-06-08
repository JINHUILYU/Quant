from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from Quantfolio.portfolio.models import Holding, PortfolioSummary, Transaction
from Quantfolio.portfolio.tracker import PortfolioTracker


# ── Helpers ─────────────────────────────────────────────────────────────

def make_csv_text() -> str:
    return (
        "date,product,type,amount,price,shares,fee,notes\n"
        "2024-01-15,002611,buy,1001.00,1.2000,833.33,1.00,定投1\n"
        "2024-02-15,002611,buy,1001.00,1.2500,800.00,1.00,定投2\n"
        "2024-06-20,002611,sell,499.50,1.3000,384.62,0.50,部分赎回\n"
    )


def make_nav_data() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=200, freq="D"),
        "nav": np.linspace(1.18, 1.35, 200),
    })


def make_synthetic_transactions() -> list[Transaction]:
    return [
        Transaction(date=pd.Timestamp("2024-01-15"), product="002611",
                    type="buy", amount=1001.00, price=1.2000,
                    shares=833.33, fee=1.00, notes="定投1"),
        Transaction(date=pd.Timestamp("2024-02-15"), product="002611",
                    type="buy", amount=1001.00, price=1.2500,
                    shares=800.00, fee=1.00, notes="定投2"),
        Transaction(date=pd.Timestamp("2024-06-20"), product="002611",
                    type="sell", amount=499.50, price=1.3000,
                    shares=384.62, fee=0.50, notes="部分赎回"),
    ]


# ── CSV loading ──────────────────────────────────────────────────────────

def test_load_transactions():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "002611.csv"
        csv_path.write_text(make_csv_text())

        tracker = PortfolioTracker()
        tracker._portfolio_dir = None  # force recompute
        # Override portfolio_dir to use temp
        tracker.portfolio_dir  # noqa: B018 -- property access
        object.__setattr__(tracker, '_portfolio_dir', Path(tmp))
        txns = tracker.load_transactions("002611")

    assert len(txns) == 3
    assert txns[0].type == "buy"
    assert txns[0].amount == 1001.00
    assert txns[2].type == "sell"
    assert txns[2].shares == 384.62


def test_load_transactions_raises_on_missing():
    tracker = PortfolioTracker()
    try:
        tracker.load_transactions("nonexistent")
        assert False, "Should have raised"
    except FileNotFoundError:
        pass


def test_load_transactions_invalid_type():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "002611.csv"
        csv_path.write_text(
            "date,product,type,amount,price,shares,fee,notes\n"
            "2024-01-15,002611,invalid,1000.00,1.2000,833.33,1.00,\n"
        )
        tracker = PortfolioTracker()
        object.__setattr__(tracker, '_portfolio_dir', Path(tmp))
        try:
            tracker.load_transactions("002611")
            assert False
        except ValueError:
            pass


# ── Daily value computation ─────────────────────────────────────────────

def test_compute_daily_value_single_buy():
    txns = [
        Transaction(date=pd.Timestamp("2024-06-01"), product="002611",
                    type="buy", amount=1000.00, price=1.0000,
                    shares=1000.00, fee=0.0, notes=""),
    ]
    nav = pd.DataFrame({
        "date": pd.date_range("2024-06-01", "2024-06-05", freq="D"),
        "nav": [1.0, 1.0, 1.0, 1.0, 1.0],
    })
    tracker = PortfolioTracker()
    daily = tracker.compute_daily_value(txns, nav)

    assert daily["shares_held"].iloc[-1] == 1000.0
    assert daily["market_value"].iloc[-1] == 1000.0
    assert daily["total_cost"].iloc[-1] == 1000.0
    assert daily["unrealized_pnl"].iloc[-1] == 0.0


def test_compute_daily_value_buy_then_sell():
    txns = [
        Transaction(date=pd.Timestamp("2024-01-01"), product="002611",
                    type="buy", amount=2000.00, price=1.0000,
                    shares=2000.00, fee=0.0, notes=""),
        Transaction(date=pd.Timestamp("2024-06-01"), product="002611",
                    type="sell", amount=750.00, price=1.5000,
                    shares=500.00, fee=0.0, notes=""),
    ]
    nav = pd.DataFrame({
        "date": pd.date_range("2024-01-01", "2024-06-02", freq="D"),
        "nav": 1.5,
    })
    tracker = PortfolioTracker()
    daily = tracker.compute_daily_value(txns, nav)

    last = daily.iloc[-1]
    assert last["shares_held"] == 1500.0
    assert abs(last["total_cost"] - 1500.0) < 0.01
    assert abs(last["market_value"] - 2250.0) < 0.01
    assert abs(last["unrealized_pnl"] - 750.0) < 0.01


def test_cumulative_invested_tracking():
    txns = make_synthetic_transactions()
    nav = make_nav_data()
    tracker = PortfolioTracker()
    daily = tracker.compute_daily_value(txns, nav)

    first_buy = daily[daily["date"] == "2024-01-15"]
    assert not first_buy.empty
    assert abs(first_buy["cumulative_invested"].iloc[0] - 1001.0) < 0.01

    second_buy = daily[daily["date"] == "2024-02-15"]
    assert not second_buy.empty
    assert abs(second_buy["cumulative_invested"].iloc[0] - 2002.0) < 0.01

    sell_row = daily[daily["date"] == "2024-06-20"]
    assert not sell_row.empty
    assert abs(sell_row["cumulative_invested"].iloc[0] - 1502.50) < 0.01


# ── Holdings ─────────────────────────────────────────────────────────────

def test_compute_holdings():
    txns = make_synthetic_transactions()
    nav = make_nav_data()
    tracker = PortfolioTracker()
    daily = tracker.compute_daily_value(txns, nav)
    holdings = tracker.compute_holdings(daily, "002611")

    assert len(holdings) == 1
    h = holdings[0]
    assert h.product == "002611"
    assert h.total_shares > 0
    assert h.avg_cost > 0
    assert h.current_price > 0
    assert abs(h.market_value - h.total_shares * h.current_price) < 0.01
    assert abs(h.cost_basis - h.total_shares * h.avg_cost) < 0.01


# ── XIRR ─────────────────────────────────────────────────────────────────

def test_compute_xirr_simple():
    txns = [
        Transaction(date=pd.Timestamp("2024-01-01"), product="002611",
                    type="buy", amount=1000.00, price=1.0,
                    shares=1000.0, fee=0.0, notes=""),
    ]
    irr = PortfolioTracker.compute_xirr(
        txns, 1100.0, pd.Timestamp("2025-01-01"),
    )
    assert abs(irr - 10.0) < 0.5


def test_compute_xirr_empty():
    irr = PortfolioTracker.compute_xirr(
        [], 100.0, pd.Timestamp("2024-01-01"),
    )
    assert irr == 0.0


# ── Max drawdown ─────────────────────────────────────────────────────────

def test_compute_max_drawdown():
    tracker = PortfolioTracker()
    series = pd.Series([100, 110, 90, 95, 105])
    dd = tracker.compute_max_drawdown(series)
    # peak 110, trough 90 → dd = (90-110)/110*100 = -18.18, abs → 18.18
    assert abs(dd - 18.18) < 0.1


# ── Full analyze flow (mocked) ──────────────────────────────────────────

def test_analyze_full_flow():
    txns = make_synthetic_transactions()
    tracker = PortfolioTracker()

    with (
        patch.object(tracker, "load_transactions", return_value=txns),
        patch.object(tracker, "fetch_nav", return_value=make_nav_data()),
    ):
        summary = tracker.analyze("002611")

    assert isinstance(summary, PortfolioSummary)
    assert summary.product == "002611"
    assert summary.total_buys == 2
    assert summary.total_sells == 1
    assert summary.total_invested > 0
    assert summary.current_value > 0
    assert summary.net_cash_flow < 0


# ── Summary output ──────────────────────────────────────────────────────

def test_summary_output():
    txns = make_synthetic_transactions()
    nav = make_nav_data()
    tracker = PortfolioTracker()
    daily = tracker.compute_daily_value(txns, nav)
    holdings = tracker.compute_holdings(daily, "002611")
    max_dd = tracker.compute_max_drawdown(daily["market_value"])
    irr = tracker.compute_xirr(
        txns, float(daily["market_value"].iloc[-1]), daily["date"].iloc[-1],
    )

    summary = PortfolioSummary(
        product="002611",
        holdings=holdings,
        transactions=txns,
        daily_value=daily,
        nav_history=nav,
        total_invested=2002.0,
        total_withdrawn=499.50,
        net_cash_flow=-1502.50,
        current_value=float(daily["market_value"].iloc[-1]),
        total_pnl=100.0,
        total_pnl_pct=5.0,
        max_drawdown_pct=max_dd,
        irr_annual_pct=irr,
        total_buys=2,
        total_sells=1,
        start_date="2024-01-15",
        end_date="2024-06-20",
    )

    text = summary.summary()
    assert isinstance(text, str)
    assert "002611" in text
    assert "持仓分析" in text


# ── Chart ────────────────────────────────────────────────────────────────

def test_portfolio_fig():
    txns = make_synthetic_transactions()
    nav = make_nav_data()
    tracker = PortfolioTracker()
    daily = tracker.compute_daily_value(txns, nav)
    holdings = tracker.compute_holdings(daily, "002611")
    summary = PortfolioSummary(
        product="002611", holdings=holdings, transactions=txns,
        daily_value=daily, nav_history=nav,
        total_invested=2002.0, total_withdrawn=499.50,
        net_cash_flow=-1502.50, current_value=1500.0,
        total_pnl=100.0, total_pnl_pct=5.0,
        max_drawdown_pct=1.5, irr_annual_pct=2.5,
        total_buys=2, total_sells=1,
        start_date="2024-01-15", end_date="2024-06-20",
    )
    fig = tracker.portfolio_fig(summary)
    assert fig is not None
    assert len(fig.data) > 0
