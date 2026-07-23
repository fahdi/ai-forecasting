"""
Tests for user_data/strategies/EnsembleSignalStrategy.py (issues #9 and #10,
PRD §4.2 R7-R10 and §7).

Guard logic is tested with a fake SignalClient — no network. Run with the
.venv-freqtrade venv's pytest:

    .venv-freqtrade/bin/pytest tests/test_ensemble_strategy.py
"""

import json
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STRATEGY_DIR = REPO_ROOT / "user_data" / "strategies"
CONFIG_PATH = REPO_ROOT / "user_data" / "config.dry.json"

sys.path.insert(0, str(STRATEGY_DIR))

# Strategy tests need the .venv-freqtrade environment; skip cleanly (instead
# of breaking collection) when run from the main app venv.
pytest.importorskip("freqtrade", reason="requires the .venv-freqtrade environment")

from EnsembleSignalStrategy import EnsembleSignalStrategy  # noqa: E402
from signal_client import SignalClient  # noqa: E402

UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]


def good_signal(**overrides) -> dict:
    """A signal that passes every API-side guard."""
    signal = {
        "pair": "BTC/USDT",
        "direction": "long",
        "confidence": 0.75,
        "horizon": "4h",
        "model_votes": {"lgbm": "long"},
        "top_features": [{"name": "rsi_14", "value": 55.0}],
        "model_version": "v1",
        "generated_at": "2026-07-23T00:00:00+00:00",
        "stale": False,
    }
    signal.update(overrides)
    return signal


class FakeSignalClient:
    """Test double for SignalClient: canned signal, no HTTP."""

    def __init__(self, signal=None):
        self.signal = signal
        self.calls = 0

    def get_signal(self, pair, candle_time):
        self.calls += 1
        return self.signal


class RaisingSignalClient:
    """Test double whose get_signal blows up (client bug / unexpected error)."""

    def get_signal(self, pair, candle_time):
        raise RuntimeError("boom")


def make_dataframe(kind: str = "calm_uptrend", bars: int = 100) -> pd.DataFrame:
    """Deterministic 1h OHLCV frames isolating one candle-side guard each.

    calm_uptrend  — close above EMA50, near-zero volatility (all guards pass)
    downtrend     — close below EMA50, near-zero volatility (EMA guard blocks)
    volatile      — close above EMA50, ~3%/bar swings so 20-bar annualized
                    volatility far exceeds the ceiling (volatility guard blocks)
    """
    i = np.arange(bars)
    if kind == "calm_uptrend":
        log_returns = np.full(bars, 0.002)
    elif kind == "downtrend":
        log_returns = np.full(bars, -0.002)
    elif kind == "volatile":
        log_returns = 0.02 + 0.03 * np.where(i % 2 == 0, 1.0, -1.0)
    else:
        raise ValueError(kind)
    close = 100.0 * np.exp(np.cumsum(log_returns))
    dates = pd.date_range(end="2026-07-23 00:00", periods=bars, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": np.full(bars, 500.0),
        }
    )


@pytest.fixture
def strategy():
    strat = EnsembleSignalStrategy({"runmode": "backtest"})
    strat.dp = MagicMock()
    return strat


def run_entry(strategy, signal_client, kind: str = "calm_uptrend") -> pd.DataFrame:
    strategy.signal_client = signal_client
    dataframe = make_dataframe(kind)
    metadata = {"pair": "BTC/USDT"}
    dataframe = strategy.populate_indicators(dataframe, metadata)
    return strategy.populate_entry_trend(dataframe, metadata)


def run_exit(strategy, signal_client) -> pd.DataFrame:
    strategy.signal_client = signal_client
    dataframe = make_dataframe("calm_uptrend")
    metadata = {"pair": "BTC/USDT"}
    dataframe = strategy.populate_indicators(dataframe, metadata)
    return strategy.populate_exit_trend(dataframe, metadata)


class TestEntryGuards:
    def test_all_guards_pass_enters_long(self, strategy):
        dataframe = run_entry(strategy, FakeSignalClient(good_signal()))
        assert dataframe["enter_long"].iloc[-1] == 1
        # Only the freshest candle may carry the live API signal.
        assert dataframe["enter_long"].iloc[:-1].sum() == 0

    def test_low_confidence_blocks_entry(self, strategy):
        signal = good_signal(confidence=0.59)  # below default threshold 0.60
        dataframe = run_entry(strategy, FakeSignalClient(signal))
        assert dataframe["enter_long"].sum() == 0

    def test_flat_direction_blocks_entry(self, strategy):
        signal = good_signal(direction="flat", confidence=0.9)
        dataframe = run_entry(strategy, FakeSignalClient(signal))
        assert dataframe["enter_long"].sum() == 0

    def test_stale_signal_blocks_entry(self, strategy):
        signal = good_signal(stale=True)
        dataframe = run_entry(strategy, FakeSignalClient(signal))
        assert dataframe["enter_long"].sum() == 0

    def test_below_ema50_blocks_entry(self, strategy):
        dataframe = run_entry(strategy, FakeSignalClient(good_signal()), "downtrend")
        assert dataframe["enter_long"].sum() == 0

    def test_high_volatility_blocks_entry(self, strategy):
        dataframe = run_entry(strategy, FakeSignalClient(good_signal()), "volatile")
        assert dataframe["enter_long"].sum() == 0

    def test_api_failure_fails_closed(self, strategy):
        # SignalClient returns None on error/timeout/non-200 -> no entry (R9).
        dataframe = run_entry(strategy, FakeSignalClient(signal=None))
        assert dataframe["enter_long"].sum() == 0

    def test_client_exception_fails_closed_and_does_not_raise(self, strategy):
        dataframe = run_entry(strategy, RaisingSignalClient())
        assert dataframe["enter_long"].sum() == 0

    def test_missing_fields_fail_closed(self, strategy):
        dataframe = run_entry(strategy, FakeSignalClient({"pair": "BTC/USDT"}))
        assert dataframe["enter_long"].sum() == 0


class TestExit:
    def test_exit_on_confident_flat_signal(self, strategy):
        signal = good_signal(direction="flat", confidence=0.7)
        dataframe = run_exit(strategy, FakeSignalClient(signal))
        assert dataframe["exit_long"].iloc[-1] == 1

    def test_no_exit_on_low_confidence_flat(self, strategy):
        signal = good_signal(direction="flat", confidence=0.5)
        dataframe = run_exit(strategy, FakeSignalClient(signal))
        assert dataframe["exit_long"].sum() == 0

    def test_no_exit_signal_while_long(self, strategy):
        dataframe = run_exit(strategy, FakeSignalClient(good_signal()))
        assert dataframe["exit_long"].sum() == 0

    def test_exit_does_not_raise_on_api_failure(self, strategy):
        dataframe = run_exit(strategy, RaisingSignalClient())
        assert dataframe["exit_long"].sum() == 0

    def test_max_hold_custom_exit_after_5_days(self, strategy):
        trade = MagicMock()
        now = pd.Timestamp("2026-07-23 00:00", tz="UTC")
        trade.open_date_utc = now - timedelta(days=5, hours=1)
        reason = strategy.custom_exit(
            pair="BTC/USDT",
            trade=trade,
            current_time=now,
            current_rate=100.0,
            current_profit=0.01,
        )
        assert reason  # any truthy exit reason ends the trade

        trade.open_date_utc = now - timedelta(days=4)
        assert not strategy.custom_exit(
            pair="BTC/USDT",
            trade=trade,
            current_time=now,
            current_rate=100.0,
            current_profit=0.01,
        )


class TestSignalClientCaching:
    def test_cached_per_pair_and_candle(self):
        session = MagicMock()
        response = MagicMock(status_code=200)
        response.json.return_value = good_signal()
        session.get.return_value = response
        client = SignalClient(base_url="http://testserver", session=session)

        t0 = pd.Timestamp("2026-07-23 00:00", tz="UTC")
        assert client.get_signal("BTC/USDT", t0) == good_signal()
        assert client.get_signal("BTC/USDT", t0) == good_signal()
        assert session.get.call_count == 1

        client.get_signal("BTC/USDT", t0 + timedelta(hours=1))  # new candle
        client.get_signal("ETH/USDT", t0)  # new pair
        assert session.get.call_count == 3

    def test_non_200_returns_none_and_is_cached(self):
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=503)
        client = SignalClient(base_url="http://testserver", session=session)
        t0 = pd.Timestamp("2026-07-23 00:00", tz="UTC")
        assert client.get_signal("BTC/USDT", t0) is None
        assert client.get_signal("BTC/USDT", t0) is None
        assert session.get.call_count == 1

    def test_network_error_returns_none(self):
        session = MagicMock()
        session.get.side_effect = ConnectionError("refused")
        client = SignalClient(base_url="http://testserver", session=session)
        t0 = pd.Timestamp("2026-07-23 00:00", tz="UTC")
        assert client.get_signal("BTC/USDT", t0) is None

    def test_timeout_passed_to_session(self):
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=503)
        client = SignalClient(base_url="http://testserver", session=session)
        client.get_signal("BTC/USDT", pd.Timestamp("2026-07-23", tz="UTC"))
        assert session.get.call_args.kwargs.get("timeout") == 5.0


class TestRiskConfiguration:
    """Issue #10: risk limits in config.dry.json and the strategy (PRD §7)."""

    @pytest.fixture
    def config(self):
        # Freqtrade loads config via rapidjson and allows // comments; strip
        # them here so stdlib json can parse the same file.
        raw = CONFIG_PATH.read_text()
        stripped = "\n".join(
            line for line in raw.splitlines() if not line.lstrip().startswith("//")
        )
        return json.loads(stripped)

    def test_max_open_trades(self, config):
        assert config["max_open_trades"] == 3

    def test_dry_run_wallet_and_stake(self, config):
        assert config["dry_run"] is True
        assert config["dry_run_wallet"] == 1000
        assert config["stake_currency"] == "USDT"

    def test_universe_pairs(self, config):
        assert config["exchange"]["pair_whitelist"] == UNIVERSE

    def test_stoploss_on_exchange(self, config):
        assert config["order_types"]["stoploss_on_exchange"] is True

    def test_timeframe_1h(self, config):
        assert config.get("timeframe", EnsembleSignalStrategy.timeframe) == "1h"

    def test_strategy_hard_stop_5_percent(self):
        assert EnsembleSignalStrategy.stoploss == -0.05

    def test_strategy_trailing_stop_enabled(self):
        assert EnsembleSignalStrategy.trailing_stop is True
        assert EnsembleSignalStrategy.trailing_stop_positive_offset > 0

    def test_protections_present(self, strategy):
        # Freqtrade only supports protections defined on the strategy (config
        # -level protections were removed) — see user_data/RISK.md.
        methods = [p["method"] for p in strategy.protections]
        assert "StoplossGuard" in methods
        drawdown_limits = [
            p["max_allowed_drawdown"]
            for p in strategy.protections
            if p["method"] == "MaxDrawdown"
        ]
        # -15% max drawdown kill (PRD §7).
        assert any(limit == pytest.approx(0.15) for limit in drawdown_limits)
        # Daily-loss circuit breaker approximation: a second MaxDrawdown guard
        # with ~24h lookback and a 5% limit (PRD §7, -5% day).
        assert any(limit == pytest.approx(0.05) for limit in drawdown_limits)
