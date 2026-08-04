"""
Database fallback for the signal candle source.

On hosts where Binance is unreachable (e.g. the US VPS gets HTTP 451), the
signal endpoint used to 500 even though Postgres holds months of ingested
klines. Candles now fall back to the database; signal staleness (R9) keeps
carrying the truth about data age, so the fail-closed contract for the bot
is unchanged.
"""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine

from app.services.kline_store import create_tables, upsert_klines
from app.services.signal_service import (
    DatabaseCandleSource,
    FallbackCandleSource,
    INTERVAL,
)


@pytest.fixture()
def kline_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/klines.db")
    create_tables(engine)
    rows = []
    # End 3 days in the past: comfortably beyond the 8h staleness threshold,
    # regardless of when the test runs.
    end = pd.Timestamp.now(tz="UTC").floor("4h") - pd.Timedelta(days=3)
    start = end - 299 * pd.Timedelta(hours=4)
    for i in range(300):
        open_time = start + i * pd.Timedelta(hours=4)
        rows.append(
            {
                "pair": "BTCUSDT",
                "interval": INTERVAL,
                "open_time_ms": int(open_time.timestamp() * 1000),
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 10.0,
            }
        )
    upsert_klines(engine, rows)
    return engine


class ExplodingSource:
    calls = 0

    def get_recent_candles(self, symbol, interval, limit):
        type(self).calls += 1
        raise RuntimeError("451 geo-blocked")


class EmptySource:
    def get_recent_candles(self, symbol, interval, limit):
        return pd.DataFrame()


class StaticSource:
    def __init__(self, frame):
        self.frame = frame
        self.calls = 0

    def get_recent_candles(self, symbol, interval, limit):
        self.calls += 1
        return self.frame


def test_database_source_serves_recent_klines(kline_engine):
    source = DatabaseCandleSource(kline_engine)
    frame = source.get_recent_candles("BTCUSDT", INTERVAL, 200)
    assert len(frame) == 200
    assert list(frame.columns) == ["open_time", "open", "high", "low", "close", "volume"]
    # tail of the series, oldest first
    assert frame["close"].iloc[-1] == 100.5 + 299
    assert frame["open_time"].is_monotonic_increasing


def test_database_source_unknown_pair_is_empty(kline_engine):
    frame = DatabaseCandleSource(kline_engine).get_recent_candles("DOGEUSDT", INTERVAL, 200)
    assert frame.empty


def test_fallback_used_when_primary_raises(kline_engine):
    source = FallbackCandleSource(ExplodingSource(), DatabaseCandleSource(kline_engine))
    frame = source.get_recent_candles("BTCUSDT", INTERVAL, 50)
    assert len(frame) == 50


def test_fallback_used_when_primary_returns_empty(kline_engine):
    source = FallbackCandleSource(EmptySource(), DatabaseCandleSource(kline_engine))
    frame = source.get_recent_candles("BTCUSDT", INTERVAL, 50)
    assert len(frame) == 50


def test_primary_wins_when_healthy(kline_engine):
    primary_frame = pd.DataFrame(
        {
            "open_time": pd.to_datetime(["2026-08-04"], utc=True),
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1.0],
        }
    )
    primary = StaticSource(primary_frame)
    fallback = StaticSource(pd.DataFrame())
    source = FallbackCandleSource(primary, fallback)
    frame = source.get_recent_candles("BTCUSDT", INTERVAL, 50)
    assert primary.calls == 1
    assert fallback.calls == 0
    assert len(frame) == 1


def test_signal_endpoint_serves_db_candles_when_binance_blocked(kline_engine):
    """End to end: Binance raising must not 500 the endpoint when the DB has
    candles; the signal comes back with the honest stale flag set (the
    seeded data is from July)."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    from app.main import app
    from app.api.v1.endpoints.models import get_health_engine
    from app.services.signal_service import (
        BinanceRestCandleSource,
        get_candle_source,
        get_predictor,
    )
    import app.services.signal_service as signal_service

    app.dependency_overrides[get_health_engine] = lambda: None  # skip prediction log
    app.dependency_overrides[get_predictor] = lambda: None  # baseline model
    try:
        with patch.object(
            BinanceRestCandleSource,
            "get_recent_candles",
            side_effect=RuntimeError("451 geo-blocked"),
        ), patch.object(signal_service, "_resolve_kline_engine", return_value=kline_engine):
            client = TestClient(app)
            response = client.get("/api/v1/signal/BTC-USDT")
    finally:
        app.dependency_overrides.pop(get_health_engine, None)
        app.dependency_overrides.pop(get_predictor, None)

    assert response.status_code == 200
    body = response.json()
    assert body["direction"] in ("long", "flat")
    assert body["stale"] is True
