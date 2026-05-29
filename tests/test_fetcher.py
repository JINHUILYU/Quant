from __future__ import annotations

from unittest.mock import patch, MagicMock
import pandas as pd

from GoldQuant.data.fetcher import SgeFetcher, DataFetchError


def make_fake_sge_data() -> pd.DataFrame:
    return pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
        "open": [480.0, 482.0, 479.0],
        "close": [482.5, 479.0, 481.0],
        "low": [479.0, 478.0, 478.5],
        "high": [483.0, 483.5, 482.0],
    })


def test_fetch_hist_normalizes_columns():
    with patch("akshare.spot_hist_sge", return_value=make_fake_sge_data()) as mock:
        fetcher = SgeFetcher()
        df = fetcher.fetch_hist("Au99.99")

    assert list(df.columns) == ["date", "open", "close", "low", "high", "symbol"]
    assert df["close"].iloc[0] == 482.5
    assert df["symbol"].iloc[0] == "Au99.99"
    assert str(df["date"].dtype).startswith("datetime64")


def test_fetch_hist_sorted_by_date():
    unsorted = pd.DataFrame({
        "date": ["2024-01-04", "2024-01-02", "2024-01-03"],
        "open": [479.0, 480.0, 482.0],
        "close": [481.0, 482.5, 479.0],
        "low": [478.5, 479.0, 478.0],
        "high": [482.0, 483.0, 483.5],
    })
    with patch("akshare.spot_hist_sge", return_value=unsorted):
        fetcher = SgeFetcher()
        df = fetcher.fetch_hist("Au99.99")

    assert df["date"].is_monotonic_increasing


def test_fetch_hist_retry_on_failure():
    call_count = [0]

    def flaky(_symbol):
        call_count[0] += 1
        if call_count[0] < 3:
            raise ConnectionError("timeout")
        return make_fake_sge_data()

    with patch("akshare.spot_hist_sge", side_effect=flaky):
        fetcher = SgeFetcher()
        df = fetcher.fetch_hist("Au99.99", retries=3)

    assert call_count[0] == 3
    assert len(df) == 3


def test_fetch_hist_raises_after_retries():
    with patch("akshare.spot_hist_sge", side_effect=ConnectionError("fail")):
        fetcher = SgeFetcher()
        try:
            fetcher.fetch_hist("Au99.99", retries=2)
            assert False, "Should have raised"
        except DataFetchError:
            pass


def test_fetch_hist_default_symbol():
    with patch("akshare.spot_hist_sge", return_value=make_fake_sge_data()) as mock:
        fetcher = SgeFetcher()
        fetcher.fetch_hist()
        mock.assert_called_once_with("Au99.99")
