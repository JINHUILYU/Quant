from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class QuantfolioConfig:
    data_dir: Path = field(default_factory=lambda: Path("data/raw"))
    portfolio_dir: str = "data/portfolio"
    default_symbol: str = "Au99.99"
    initial_capital: float = 100_000.0
    commission_pct: float = 0.0008  # SGE ~0.08%
    slippage_pct: float = 0.0002

    # Indicator defaults
    sma_short: int = 5
    sma_long: int = 20
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14

    # Long-term strategy defaults
    lt_sma_short: int = 50
    lt_sma_long: int = 200
    lt_rsi_period: int = 21
    lt_rsi_overbought: float = 80.0
    lt_rsi_oversold: float = 20.0
    lt_bollinger_period: int = 50
    lt_bollinger_std: float = 3.0

    @property
    def data_dir_abs(self) -> Path:
        p = Path(self.data_dir)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent.parent / p
        return p

    @property
    def portfolio_dir_abs(self) -> Path:
        p = Path(self.portfolio_dir)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent.parent / p
        return p
