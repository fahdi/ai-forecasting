"""
Trade-signal generation service (PRD §4.1 R3, issue #7).

Serves long/flat signals for the configured spot universe. The model here is
the versioned baseline (EMA momentum) — the trained ensemble replaces it via
the same interface (issues #5/#6). Candles come from an injectable
CandleSource so the endpoint is testable without network access.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

import numpy as np
import pandas as pd

from app.models.crypto_features import WARMUP_BARS

# v1 spot universe (PRD §4.1 R2): exchange symbol -> canonical pair name.
UNIVERSE: Dict[str, str] = {
    "BTCUSDT": "BTC/USDT",
    "ETHUSDT": "ETH/USDT",
    "SOLUSDT": "SOL/USDT",
    "BNBUSDT": "BNB/USDT",
}

INTERVAL = "4h"
INTERVAL_DELTA = pd.Timedelta(hours=4)
# R9: a signal older than 2 evaluation cycles is stale -> no new entries.
STALE_AFTER = 2 * INTERVAL_DELTA
CANDLE_LIMIT = 200

MODEL_VERSION = "baseline-momentum-v0"


class InsufficientDataError(Exception):
    pass


class CandleSource(Protocol):
    def get_recent_candles(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """Return closed OHLCV candles, oldest first."""
        ...


class BinanceRestCandleSource:
    """Default source: Binance public klines REST API (no auth required)."""

    BASE_URL = "https://api.binance.com/api/v3/klines"

    def get_recent_candles(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        import httpx

        response = httpx.get(
            self.BASE_URL,
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10.0,
        )
        response.raise_for_status()
        rows = response.json()
        frame = pd.DataFrame(
            [
                {
                    "open_time": pd.Timestamp(row[0], unit="ms", tz="UTC"),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": pd.Timestamp(row[6], unit="ms", tz="UTC"),
                }
                for row in rows
            ]
        )
        # Drop the still-open final candle: only closed bars feed the model.
        now = pd.Timestamp.now(tz="UTC")
        frame = frame[frame["close_time"] <= now]
        return frame.drop(columns=["close_time"]).reset_index(drop=True)


def get_candle_source() -> CandleSource:
    """FastAPI dependency — override in tests."""
    return BinanceRestCandleSource()


def normalize_pair(raw: str) -> Optional[str]:
    """Map user input ('BTC-USDT', 'btc/usdt', 'BTCUSDT') to an exchange symbol."""
    cleaned = raw.upper().replace("-", "").replace("/", "").replace("_", "")
    if not cleaned.isalnum():
        return None
    return cleaned if cleaned in UNIVERSE else None


@dataclass
class Signal:
    pair: str
    direction: str  # "long" | "flat" — spot-only, never "short"
    confidence: float
    horizon: str
    model_votes: Dict[str, str]
    top_features: List[Dict[str, Any]]
    model_version: str
    generated_at: str
    stale: bool


def _is_stale(last_open_time: pd.Timestamp) -> bool:
    last_close = last_open_time + INTERVAL_DELTA
    return (pd.Timestamp.now(tz="UTC") - last_close) > STALE_AFTER


def generate_signal(symbol: str, candles: pd.DataFrame) -> Signal:
    """Baseline momentum model: long iff EMA12 > EMA26 and close > EMA50."""
    if len(candles) <= WARMUP_BARS:
        raise InsufficientDataError(
            f"insufficient history for {symbol}: "
            f"{len(candles)} bars, need > {WARMUP_BARS}"
        )

    close = candles["close"]
    ema_12 = close.ewm(span=12, adjust=True).mean().iloc[-1]
    ema_26 = close.ewm(span=26, adjust=True).mean().iloc[-1]
    ema_50 = close.ewm(span=50, adjust=True).mean().iloc[-1]
    last_close = close.iloc[-1]

    ema_trend_long = ema_12 > ema_26
    above_ema_50 = last_close > ema_50
    direction = "long" if (ema_trend_long and above_ema_50) else "flat"

    # Confidence from the normalized EMA spread, squashed to (0, 1); for a
    # flat call, confidence is the confidence in *being flat*.
    spread = float((ema_12 - ema_26) / last_close)
    long_confidence = float(1.0 / (1.0 + np.exp(-400.0 * spread)))
    confidence = long_confidence if direction == "long" else 1.0 - long_confidence
    confidence = min(1.0, max(0.0, confidence))

    return Signal(
        pair=UNIVERSE[symbol],
        direction=direction,
        confidence=confidence,
        horizon=INTERVAL,
        model_votes={
            "ema_trend": "long" if ema_trend_long else "flat",
            "price_above_ema_50": "long" if above_ema_50 else "flat",
        },
        top_features=[
            {"name": "ema_12_26_spread", "value": spread},
            {"name": "close_over_ema_50", "value": float(last_close / ema_50)},
        ],
        model_version=MODEL_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        stale=_is_stale(candles["open_time"].iloc[-1]),
    )
