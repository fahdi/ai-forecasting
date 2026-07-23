"""
G0 walk-forward backtest engine (issue #11, PRD §8).

Long/flat simulation with per-side fees and slippage. Discipline rules:
the position for bar t is decided from the signal at bar t-1 (entered at
that bar's close) — never from the same bar's outcome.
"""

from typing import Dict

import numpy as np
import pandas as pd

BINANCE_TAKER_FEE = 0.001      # 0.1% per side
DEFAULT_SLIPPAGE = 0.0005      # 0.05% per side


def simulate_long_flat(
    close: pd.Series,
    prob_long: pd.Series,
    threshold: float,
    fee_per_side: float = BINANCE_TAKER_FEE,
    slippage_per_side: float = DEFAULT_SLIPPAGE,
    stop_loss: float = None,
    max_hold_bars: int = None,
) -> Dict:
    """Simulate a long/flat strategy on one price series.

    Entry: prob_long[t] >= threshold and currently flat -> enter at close[t].
    Exit: prob_long[t] < threshold, stop-loss breach (measured at bar close),
    or max-hold timeout -> exit at close[t].
    Returns dict with the equity curve (start 1.0), trade count, fee drag.
    """
    cost = fee_per_side + slippage_per_side
    n = len(close)
    equity = np.ones(n)
    current = 1.0
    in_position = False
    entry_price = None
    bars_held = 0
    n_trades = 0
    fee_paid = 0.0

    for t in range(n):
        if in_position:
            bar_return = close.iloc[t] / close.iloc[t - 1]
            current *= bar_return
            bars_held += 1

            stop_hit = (
                stop_loss is not None
                and close.iloc[t] / entry_price - 1.0 <= -stop_loss
            )
            timeout = max_hold_bars is not None and bars_held >= max_hold_bars
            wants_exit = prob_long.iloc[t] < threshold
            if stop_hit or timeout or wants_exit:
                fee = current * cost
                current -= fee
                fee_paid += fee
                in_position = False
                entry_price = None
        if not in_position and t < n - 1 and prob_long.iloc[t] >= threshold:
            fee = current * cost
            current -= fee
            fee_paid += fee
            in_position = True
            entry_price = close.iloc[t]
            bars_held = 0
            n_trades += 1
        equity[t] = current

    return {
        "equity": pd.Series(equity, index=close.index),
        "n_trades": n_trades,
        "fee_drag": fee_paid,
    }


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    drawdown = 1.0 - equity / peak
    return float(drawdown.max())


def sharpe_ratio(equity: pd.Series, periods_per_year: int) -> float:
    returns = equity.pct_change().dropna()
    if len(returns) == 0 or returns.std(ddof=1) == 0:
        return 0.0
    return float(returns.mean() / returns.std(ddof=1) * np.sqrt(periods_per_year))
