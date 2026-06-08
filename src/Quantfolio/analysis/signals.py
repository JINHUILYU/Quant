from __future__ import annotations

import pandas as pd
import numpy as np


class SignalEvaluator:
    """Vectorized signal generation from indicator series."""

    @staticmethod
    def crossover(series1: pd.Series, series2: pd.Series) -> pd.Series:
        """1 when s1 crosses above s2, -1 when crosses below, 0 otherwise."""
        above = series1 > series2
        prev_above = above.shift(1).fillna(False)
        cross_up = above & ~prev_above
        cross_down = ~above & prev_above
        return pd.Series(
            np.select([cross_up, cross_down], [1, -1], default=0),
            index=series1.index,
        )

    @staticmethod
    def cross_above(series: pd.Series, level: float) -> pd.Series:
        """1 when series crosses above level."""
        above = series > level
        prev_above = above.shift(1).fillna(False)
        cross = above & ~prev_above
        return pd.Series(np.where(cross, 1, 0), index=series.index)

    @staticmethod
    def cross_below(series: pd.Series, level: float) -> pd.Series:
        """1 when series crosses below level."""
        below = series < level
        prev_below = below.shift(1).fillna(False)
        cross = below & ~prev_below
        return pd.Series(np.where(cross, 1, 0), index=series.index)
