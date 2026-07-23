"""
Tests for the G0 walk-forward backtest engine (issue #11, PRD §8).

Money math must be hand-checkable: fees per side, positions entered on the
bar AFTER the signal (no lookahead), drawdown from the equity peak.
"""

import numpy as np
import pandas as pd
import pytest

from app.backtest.engine import (
    max_drawdown,
    sharpe_ratio,
    simulate_long_flat,
)


def series(values):
    return pd.Series(values, dtype=float)


class TestSimulateLongFlat:
    def test_stays_flat_when_prob_below_threshold(self):
        close = series([100, 110, 121, 133.1])
        prob = series([0.1, 0.1, 0.1, 0.1])
        result = simulate_long_flat(close, prob, threshold=0.6,
                                    fee_per_side=0.0, slippage_per_side=0.0)
        assert result["equity"].iloc[-1] == pytest.approx(1.0)
        assert result["n_trades"] == 0

    def test_signal_acts_on_next_bar_no_lookahead(self):
        # Signal fires at bar 1; the position must capture the bar1->bar2
        # return and NOT the bar0->bar1 return.
        close = series([100.0, 200.0, 220.0, 220.0])
        prob = series([0.0, 1.0, 0.0, 0.0])
        result = simulate_long_flat(close, prob, threshold=0.5,
                                    fee_per_side=0.0, slippage_per_side=0.0)
        # Enters at close[1]=200, exits at close[2]=220: +10%, not +100%.
        assert result["equity"].iloc[-1] == pytest.approx(1.10)
        assert result["n_trades"] == 1

    def test_fees_charged_per_side(self):
        close = series([100.0, 100.0, 100.0, 100.0])
        prob = series([0.0, 1.0, 0.0, 0.0])
        result = simulate_long_flat(close, prob, threshold=0.5,
                                    fee_per_side=0.001, slippage_per_side=0.0005)
        # Flat prices: the only P&L is -0.15% on entry and -0.15% on exit.
        expected = (1 - 0.0015) ** 2
        assert result["equity"].iloc[-1] == pytest.approx(expected, rel=1e-9)
        assert result["fee_drag"] == pytest.approx(1 - expected, rel=1e-6)

    def test_stop_loss_exits_position(self):
        close = series([100.0, 100.0, 80.0, 80.0, 80.0])
        prob = series([0.0, 1.0, 1.0, 1.0, 1.0])
        result = simulate_long_flat(close, prob, threshold=0.5, stop_loss=0.05,
                                    fee_per_side=0.0, slippage_per_side=0.0)
        # -20% bar breaches the 5% stop: realized at the bar close (worst
        # case, no intrabar fill assumed), then stays out while prob high?
        # Re-entry allowed next bar; equity after stop = 0.8.
        assert result["equity"].iloc[2] == pytest.approx(0.8)
        assert result["n_trades"] >= 1


class TestMetrics:
    def test_max_drawdown_golden(self):
        equity = series([1.0, 1.2, 0.9, 1.1, 1.3, 1.0])
        assert max_drawdown(equity) == pytest.approx(0.25)  # 1.2 -> 0.9

    def test_max_drawdown_monotonic_rise_is_zero(self):
        assert max_drawdown(series([1.0, 1.1, 1.2])) == 0.0

    def test_sharpe_zero_for_flat_equity(self):
        assert sharpe_ratio(series([1.0, 1.0, 1.0, 1.0]), periods_per_year=6*365) == 0.0

    def test_sharpe_positive_for_steady_gains(self):
        equity = series(np.exp(np.linspace(0, 0.5, 200)))
        noise = pd.Series(1 + np.sin(np.arange(200)) * 1e-4)
        assert sharpe_ratio(equity * noise, periods_per_year=6 * 365) > 0
