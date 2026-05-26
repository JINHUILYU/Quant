from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from goldquant.config import GoldQuantConfig


class Strategy(ABC):
    """Abstract base for trading strategies.

    Subclasses auto-register in `Strategy.registry` by name.
    """

    registry: dict[str, type[Strategy]] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        Strategy.registry[cls.__name__] = cls

    def __init__(self, config: GoldQuantConfig | None = None):
        self.cfg = config or GoldQuantConfig()
        self.name = self.__class__.__name__

    @abstractmethod
    def init(self, data: pd.DataFrame) -> pd.DataFrame:
        """Attach indicators to data. Return DataFrame with added columns."""
        ...

    @abstractmethod
    def next(self, i: int, row: pd.Series, context: dict[str, Any]) -> int:
        """Called per bar. Returns 1 (buy/open long), -1 (sell/close long), 0 (hold)."""
        ...
