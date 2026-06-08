from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import numpy as np

from Quantfolio.backtest.engine import TradeRecord


@dataclass
class BacktestResult:
    total_return_pct: float
    annualized_return_pct: float
    annualized_volatility_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    total_trades: int
    win_rate_pct: float
    profit_factor: float
    avg_trade_pnl_pct: float
    avg_bars_held: float
    equity_curve: pd.DataFrame
    trades: list[TradeRecord]
    strategy: str
    symbol: str

    def summary(self) -> str:
        lines = [
            f"Strategy: {self.strategy}  |  Symbol: {self.symbol}",
            f"{'─' * 55}",
            f"Total Return:     {self.total_return_pct:>8.2f}%",
            f"Annualized Return:{self.annualized_return_pct:>8.2f}%",
            f"Annualized Vol:   {self.annualized_volatility_pct:>8.2f}%",
            f"Sharpe Ratio:     {self.sharpe_ratio:>8.2f}",
            f"Max Drawdown:     {self.max_drawdown_pct:>8.2f}%",
            f"{'─' * 55}",
            f"Total Trades:     {self.total_trades:>8d}",
            f"Win Rate:         {self.win_rate_pct:>8.1f}%",
            f"Profit Factor:    {self.profit_factor:>8.2f}",
            f"Avg Trade PnL:    {self.avg_trade_pnl_pct:>8.2f}%",
            f"Avg Bars Held:    {self.avg_bars_held:>8.1f}",
        ]
        return "\n".join(lines)


def compute_metrics(result: dict[str, Any]) -> BacktestResult:
    equity = result["equity_curve"]
    trades: list[TradeRecord] = result["trades"]
    initial_capital = result["initial_capital"]

    eq = equity["equity"].values
    total_return = (eq[-1] / initial_capital - 1) * 100

    daily_ret = pd.Series(np.diff(eq) / eq[:-1])
    daily_ret = daily_ret.replace([np.inf, -np.inf], np.nan).dropna()

    n_days = len(eq)
    ann_return = ((1 + total_return / 100) ** (252 / n_days) - 1) * 100 if n_days > 0 else 0
    ann_vol = daily_ret.std() * np.sqrt(252) * 100

    sharpe = (ann_return / ann_vol) if ann_vol > 0 else 0.0

    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak * 100
    max_dd = abs(dd.min()) if len(dd) > 0 else 0.0

    if trades:
        wins = [t for t in trades if t.pnl > 0]
        win_rate = len(wins) / len(trades) * 100
        total_gain = sum(t.pnl for t in wins)
        total_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
        profit_factor = total_gain / total_loss if total_loss > 0 else float("inf")
        avg_pnl = sum(t.pnl_pct for t in trades) / len(trades)
        avg_bars = sum(t.bars_held for t in trades) / len(trades)
    else:
        win_rate = 0.0
        profit_factor = 0.0
        avg_pnl = 0.0
        avg_bars = 0.0

    return BacktestResult(
        total_return_pct=total_return,
        annualized_return_pct=ann_return,
        annualized_volatility_pct=ann_vol,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_dd,
        total_trades=len(trades),
        win_rate_pct=win_rate,
        profit_factor=profit_factor,
        avg_trade_pnl_pct=avg_pnl,
        avg_bars_held=avg_bars,
        equity_curve=equity,
        trades=trades,
        strategy=result["strategy"],
        symbol=result["symbol"],
    )
