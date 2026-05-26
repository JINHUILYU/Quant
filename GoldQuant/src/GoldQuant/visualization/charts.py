from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from GoldQuant.backtest.engine import TradeRecord


def price_fig(
    df: pd.DataFrame,
    indicators: list[str] | None = None,
    title: str = "Au99.99 Spot Gold",
) -> go.Figure:
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["close"], mode="lines",
        name="Close", line=dict(color="gold", width=1.5),
    ))

    if indicators:
        colors = ["blue", "orange", "green", "red", "purple", "cyan"]
        for idx, ind in enumerate(indicators):
            if ind in df.columns:
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df[ind], mode="lines",
                    name=ind, line=dict(color=colors[idx % len(colors)], width=1, dash="dot"),
                ))

    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Price (CNY/g)",
        hovermode="x unified",
        template="plotly_white",
    )
    return fig


def equity_fig(result: dict, title: str | None = None) -> go.Figure:
    eq = result["equity_curve"]
    initial = result["initial_capital"]

    equity_arr = eq["equity"].values
    peak = pd.Series(equity_arr).cummax().values
    dd_pct = (equity_arr - peak) / peak * 100

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=("Equity Curve", "Drawdown %"),
    )

    fig.add_trace(go.Scatter(
        x=eq["date"], y=equity_arr, mode="lines",
        name="Equity", line=dict(color="steelblue", width=1.5),
        fill="tozeroy", fillcolor="rgba(70,130,180,0.1)",
    ), row=1, col=1)

    fig.add_hline(y=initial, line_dash="dash", line_color="gray",
                  annotation_text="Initial Capital", row=1, col=1)

    fig.add_trace(go.Scatter(
        x=eq["date"], y=dd_pct, mode="lines",
        name="Drawdown", line=dict(color="firebrick", width=1),
        fill="tozeroy", fillcolor="rgba(178,34,34,0.15)",
    ), row=2, col=1)

    title = title or f"{result['strategy']} - {result['symbol']}"
    fig.update_layout(
        title=title,
        hovermode="x unified",
        template="plotly_white",
        showlegend=False,
    )
    fig.update_yaxes(title_text="Equity (CNY)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown %", row=2, col=1)
    return fig


def trades_fig(
    df: pd.DataFrame,
    trades: list[TradeRecord],
    indicators: list[str] | None = None,
    title: str | None = None,
) -> go.Figure:
    fig = price_fig(df, indicators, title or "Trades")

    for t in trades:
        fig.add_trace(go.Scatter(
            x=[t.entry_date], y=[t.entry_price], mode="markers",
            marker=dict(symbol="triangle-up", size=10, color="green"),
            name="Buy", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=[t.exit_date], y=[t.exit_price], mode="markers",
            marker=dict(symbol="triangle-down", size=10, color="red"),
            name="Sell", showlegend=False,
        ))

    return fig


def combined_fig(
    df: pd.DataFrame,
    result: dict,
    indicators: list[str] | None = None,
    title: str | None = None,
) -> go.Figure:
    eq = result["equity_curve"]
    initial = result["initial_capital"]
    equity_arr = eq["equity"].values
    peak = pd.Series(equity_arr).cummax().values
    dd_pct = (equity_arr - peak) / peak * 100

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.45, 0.35, 0.2],
        subplot_titles=("Price & Trades", "Equity Curve", "Drawdown"),
    )

    # Row 1: Price + indicators + trades
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["close"], mode="lines",
        name="Close", line=dict(color="gold", width=1.2),
    ), row=1, col=1)

    if indicators:
        colors = ["blue", "orange", "green", "red", "purple"]
        for idx, ind in enumerate(indicators):
            if ind in df.columns:
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df[ind], mode="lines",
                    name=ind, line=dict(color=colors[idx % len(colors)], width=0.8, dash="dot"),
                ), row=1, col=1)

    for t in result["trades"]:
        fig.add_trace(go.Scatter(
            x=[t.entry_date], y=[t.entry_price], mode="markers",
            marker=dict(symbol="triangle-up", size=8, color="green"),
            name="Buy", showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=[t.exit_date], y=[t.exit_price], mode="markers",
            marker=dict(symbol="triangle-down", size=8, color="red"),
            name="Sell", showlegend=False,
        ), row=1, col=1)

    # Row 2: Equity curve
    fig.add_trace(go.Scatter(
        x=eq["date"], y=equity_arr, mode="lines",
        name="Equity", line=dict(color="steelblue", width=1.5),
        fill="tozeroy", fillcolor="rgba(70,130,180,0.1)",
    ), row=2, col=1)
    fig.add_hline(y=initial, line_dash="dash", line_color="gray", row=2, col=1)

    # Row 3: Drawdown
    fig.add_trace(go.Scatter(
        x=eq["date"], y=dd_pct, mode="lines",
        name="DD%", line=dict(color="firebrick", width=1),
        fill="tozeroy", fillcolor="rgba(178,34,34,0.15)",
    ), row=3, col=1)

    title = title or f"{result['strategy']} Backtest - {result['symbol']}"
    fig.update_layout(
        title=title,
        hovermode="x unified",
        template="plotly_white",
        height=900,
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Equity", row=2, col=1)
    fig.update_yaxes(title_text="DD%", row=3, col=1)
    return fig
