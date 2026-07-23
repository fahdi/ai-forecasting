"""
EnsembleSignalStrategy — Freqtrade execution layer for the ensemble signal
API (issues #9/#10, PRD §4.2 R7-R10 and §7).

On each 1h candle the strategy fetches GET /api/v1/signal/{pair} (base URL
from env SIGNAL_API_URL, default http://localhost:8000) and enters long only
when ALL of the following hold:

  1. signal direction == "long"
  2. signal confidence >= buy_confidence_threshold (hyperopt-able, 0.60)
  3. signal stale == false (R9)
  4. close > EMA(50) of the 1h candles          (trend guard, R8b)
  5. 20-bar annualized volatility < volatility_ceiling (volatility guard, R8c)

FAIL-CLOSED (R9): any API error, timeout, non-200, missing field, or
stale=true means no entry. populate_* never raises. Exits go the safe
direction (toward flat), so the exit signal fires on a confident "flat"
even if the signal is stale; positions are otherwise managed by the -5%
exchange-side stop, the trailing stop, and a 5-day max-hold custom exit.

NOTE on backtesting: the API serves the signal for "now", so entry/exit
signals are only applied to the freshest candle. Historical backtests need a
replay-capable signal source; until then use dry-run for evaluation.
"""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from freqtrade.strategy import DecimalParameter, IStrategy

# Freqtrade loads strategy modules by file path; make sibling imports work
# both under freqtrade and under plain pytest.
sys.path.append(str(Path(__file__).parent))

from signal_client import SignalClient  # noqa: E402

logger = logging.getLogger(__name__)

# sqrt(hours per year): annualizes the std-dev of 1h log returns.
ANNUALIZATION_1H = float(np.sqrt(24 * 365))


class EnsembleSignalStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 60  # EMA(50) warm-up

    # --- Exits / risk (issue #10, PRD §7) ---
    # Hard stop: -5%, placed on the exchange via order_types in
    # user_data/config.dry.json (stoploss_on_exchange, R10).
    stoploss = -0.05
    # Trailing stop: once +4% in profit, trail at 2% below the peak.
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True
    # ROI table disabled — exits come from the exit signal, stops, and the
    # 5-day max-hold in custom_exit().
    minimal_roi = {"0": 100}
    use_exit_signal = True
    exit_profit_only = False

    max_hold = timedelta(days=5)

    # --- Entry guards (hyperopt-able) ---
    buy_confidence_threshold = DecimalParameter(
        0.50, 0.90, default=0.60, decimals=2, space="buy", optimize=True
    )
    # Ceiling on 20-bar annualized volatility (1.50 = 150% annualized).
    volatility_ceiling = DecimalParameter(
        0.50, 3.00, default=1.50, decimals=2, space="buy", optimize=True
    )
    # Exit-side confidence is fixed: a confident "flat" closes the position.
    exit_confidence_threshold = 0.60

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.signal_client = SignalClient()

    @property
    def protections(self):
        # Freqtrade only supports protections on the strategy (config-level
        # protections were removed). PRD §7 mapping and known gaps are
        # documented in user_data/RISK.md.
        return [
            {
                # 4 stop-losses across all pairs within 24h -> halt 24h.
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 4,
                "stop_duration_candles": 24,
                "only_per_pair": False,
            },
            {
                # Daily -5% circuit breaker (approximation): 24h rolling
                # closed-trade drawdown >= 5% -> halt ~60 days (i.e. until a
                # human intervenes — see RISK.md gap #1/#2).
                "method": "MaxDrawdown",
                "lookback_period_candles": 24,
                "trade_limit": 1,
                "max_allowed_drawdown": 0.05,
                "stop_duration_candles": 1440,
            },
            {
                # -15% max drawdown kill: 30-day lookback -> halt ~5 years
                # (effectively permanent, stakeholder restart required).
                "method": "MaxDrawdown",
                "lookback_period_candles": 720,
                "trade_limit": 1,
                "max_allowed_drawdown": 0.15,
                "stop_duration_candles": 43200,
            },
        ]

    # --- Indicators ---

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["ema50"] = dataframe["close"].ewm(span=50, adjust=False).mean()
        log_returns = np.log(dataframe["close"] / dataframe["close"].shift(1))
        dataframe["volatility_ann"] = (
            log_returns.rolling(20).std() * ANNUALIZATION_1H
        )
        return dataframe

    # --- Entry ---

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["enter_long"] = 0
        try:
            if self._entry_allowed(dataframe, metadata["pair"]):
                dataframe.iloc[-1, dataframe.columns.get_loc("enter_long")] = 1
        except Exception:
            # FAIL-CLOSED (R9): never raise, never trade blind.
            logger.exception(
                "Entry evaluation failed for %s — failing closed, no entry",
                metadata.get("pair"),
            )
            dataframe["enter_long"] = 0
        return dataframe

    def _entry_allowed(self, dataframe: pd.DataFrame, pair: str) -> bool:
        last = dataframe.iloc[-1]
        signal = self.signal_client.get_signal(pair, last["date"])
        if signal is None:
            logger.info("%s: no signal (API unavailable) — no entry (R9)", pair)
            return False
        if signal.get("stale", True):
            logger.info("%s: signal stale — no entry (R9)", pair)
            return False
        if signal.get("direction") != "long":
            return False
        confidence = signal.get("confidence")
        if not isinstance(confidence, (int, float)) or (
            confidence < self.buy_confidence_threshold.value
        ):
            logger.info("%s: confidence %s below threshold — no entry", pair, confidence)
            return False
        ema50 = last["ema50"]
        if pd.isna(ema50) or not last["close"] > ema50:
            logger.info("%s: close below EMA50 — trend guard blocked entry", pair)
            return False
        volatility = last["volatility_ann"]
        if pd.isna(volatility) or not volatility < self.volatility_ceiling.value:
            logger.info(
                "%s: annualized volatility %.2f above ceiling — no entry",
                pair,
                float("nan") if pd.isna(volatility) else volatility,
            )
            return False
        return True

    # --- Exit ---

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["exit_long"] = 0
        try:
            last = dataframe.iloc[-1]
            signal = self.signal_client.get_signal(metadata["pair"], last["date"])
            # Exiting is the safe direction, so a stale "flat" still exits.
            if (
                signal is not None
                and signal.get("direction") == "flat"
                and isinstance(signal.get("confidence"), (int, float))
                and signal["confidence"] >= self.exit_confidence_threshold
            ):
                dataframe.iloc[-1, dataframe.columns.get_loc("exit_long")] = 1
        except Exception:
            logger.exception(
                "Exit evaluation failed for %s — leaving exits to stop/trailing/max-hold",
                metadata.get("pair"),
            )
            dataframe["exit_long"] = 0
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        """Time-based max hold: close any position older than 5 days (R8)."""
        if current_time - trade.open_date_utc > self.max_hold:
            return "max_hold_5d"
        return None
