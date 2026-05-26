from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from goldquant.config import GoldQuantConfig

logger = logging.getLogger(__name__)


class LocalDataStore:
    """Local CSV persistence for gold price data."""

    def __init__(self, config: GoldQuantConfig | None = None):
        self.cfg = config or GoldQuantConfig()
        self._dir: Path | None = None

    @property
    def data_dir(self) -> Path:
        if self._dir is None:
            self._dir = self.cfg.data_dir_abs
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir

    def _path(self, symbol: str) -> Path:
        return self.data_dir / f"{symbol}.csv"

    def save(self, df: pd.DataFrame, symbol: str | None = None) -> Path:
        symbol = symbol or self.cfg.default_symbol
        path = self._path(symbol)
        df.to_csv(path, index=False)
        logger.info("Saved %d rows to %s", len(df), path)
        return path

    def load(self, symbol: str | None = None) -> pd.DataFrame:
        symbol = symbol or self.cfg.default_symbol
        path = self._path(symbol)
        if not path.exists():
            raise FileNotFoundError(f"No cached data for {symbol} at {path}")
        df = pd.read_csv(path, parse_dates=["date"])
        logger.info("Loaded %d rows from %s", len(df), path)
        return df

    def exists(self, symbol: str | None = None) -> bool:
        return self._path(symbol or self.cfg.default_symbol).exists()

    def get_date_range(self, symbol: str | None = None) -> tuple[str, str] | None:
        symbol = symbol or self.cfg.default_symbol
        if not self.exists(symbol):
            return None
        df = pd.read_csv(self._path(symbol), usecols=["date"], parse_dates=["date"])
        return df["date"].min().strftime("%Y-%m-%d"), df["date"].max().strftime("%Y-%m-%d")

    def update(self, df_new: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame:
        symbol = symbol or self.cfg.default_symbol
        if self.exists(symbol):
            df_old = self.load(symbol)
            merged = pd.concat([df_old, df_new], ignore_index=True)
            merged = merged.drop_duplicates(subset="date", keep="last")
            merged = merged.sort_values("date").reset_index(drop=True)
        else:
            merged = df_new.copy()
        self.save(merged, symbol)
        return merged
