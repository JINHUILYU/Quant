from __future__ import annotations

import time
import logging
from typing import Optional

import pandas as pd
import akshare as ak

from goldquant.config import GoldQuantConfig

logger = logging.getLogger(__name__)


class DataFetchError(Exception):
    """Raised when data fetching fails after all retries."""


class SgeFetcher:
    """Wrapper around AkShare for Shanghai Gold Exchange data."""

    def __init__(self, config: GoldQuantConfig | None = None):
        self.cfg = config or GoldQuantConfig()

    def fetch_hist(self, symbol: str | None = None, retries: int = 3) -> pd.DataFrame:
        symbol = symbol or self.cfg.default_symbol
        last_err: Optional[Exception] = None

        for attempt in range(retries):
            try:
                df = ak.spot_hist_sge(symbol)
                break
            except Exception as e:
                last_err = e
                wait = 2 ** attempt
                logger.warning(
                    "spot_hist_sge(%s) attempt %d/%d failed: %s. Retrying in %ds...",
                    symbol, attempt + 1, retries, e, wait,
                )
                time.sleep(wait)
        else:
            raise DataFetchError(
                f"Failed to fetch {symbol} after {retries} attempts"
            ) from last_err

        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df["symbol"] = symbol
        df = df.sort_values("date").reset_index(drop=True)
        return df

    @staticmethod
    def fetch_symbol_table() -> pd.DataFrame:
        return ak.spot_symbol_table_sge()
