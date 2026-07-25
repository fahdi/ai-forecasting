"""
Tests for the chart data endpoints (candlestick view + prediction overlay).

GET /api/v1/chart/{pair}/candles      — OHLCV from the kline store
GET /api/v1/chart/{pair}/predictions  — model-view prob_long series (active
ensemble over stored candles, in-sample boundary included) + logged
predictions with realized outcomes.
"""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.v1.endpoints.chart import get_chart_engine
from app.services.kline_store import create_tables, upsert_klines
from app.services.model_health import record_prediction
from app.services.signal_service import get_predictor

FOUR_H_MS = 4 * 3_600_000


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    create_tables(eng)
    return eng


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_chart_engine] = lambda: engine
    app.dependency_overrides[get_predictor] = lambda: None
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


def seed_candles(engine, pair="BTCUSDT", n=120, start_ms=0, seed=5):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.01, n)))
    rows = [
        {
            "pair": pair, "interval": "4h",
            "open_time_ms": start_ms + i * FOUR_H_MS,
            "open": float(close[i]), "high": float(close[i] * 1.01),
            "low": float(close[i] * 0.99), "close": float(close[i]),
            "volume": float(rng.uniform(10, 100)),
        }
        for i in range(n)
    ]
    upsert_klines(engine, rows)
    return rows


class TestCandles:
    def test_candles_shape_and_time_unit(self, client, engine):
        rows = seed_candles(engine, n=50)
        body = client.get("/api/v1/chart/BTC-USDT/candles?limit=30").json()
        assert body["pair"] == "BTC/USDT"
        assert body["interval"] == "4h"
        assert len(body["candles"]) == 30
        first = body["candles"][0]
        assert {"time", "open", "high", "low", "close", "volume"} <= set(first)
        # lightweight-charts wants unix SECONDS; returns the most recent bars.
        assert body["candles"][-1]["time"] == rows[-1]["open_time_ms"] // 1000
        times = [c["time"] for c in body["candles"]]
        assert times == sorted(times)

    def test_unknown_pair_404(self, client, engine):
        seed_candles(engine)
        assert client.get("/api/v1/chart/DOGE-USDT/candles").status_code == 404

    def test_no_data_503(self, client, engine):
        assert client.get("/api/v1/chart/BTC-USDT/candles").status_code == 503

    def test_limit_capped(self, client, engine):
        seed_candles(engine, n=50)
        response = client.get("/api/v1/chart/BTC-USDT/candles?limit=5000")
        assert response.status_code == 422


class TestPredictions:
    def test_logged_predictions_with_outcomes(self, client, engine):
        seed_candles(engine, n=60)
        record_prediction(engine, pair="BTCUSDT", interval="4h",
                          model_version="m1",
                          predicted_at_ms=10 * FOUR_H_MS + 999,  # mid-candle
                          direction="long", confidence=0.7,
                          horizon_ms=FOUR_H_MS, price=100.0)
        body = client.get("/api/v1/chart/BTC-USDT/predictions").json()
        assert len(body["logged"]) == 1
        entry = body["logged"][0]
        # Snapped to the candle open time, in unix seconds.
        assert entry["time"] == 10 * FOUR_H_MS // 1000
        assert entry["direction"] == "long"
        assert entry["realized"] is None  # unresolved yet

    def test_logged_predictions_deduped_per_candle(self, client, engine):
        """Polling records many predictions per candle; the chart wants the
        latest one per candle, not a stack of markers."""
        seed_candles(engine, n=60)
        for offset, direction in [(100, "long"), (2000, "long"), (3000, "flat")]:
            record_prediction(engine, pair="BTCUSDT", interval="4h",
                              model_version="m1",
                              predicted_at_ms=10 * FOUR_H_MS + offset,
                              direction=direction, confidence=0.6,
                              horizon_ms=FOUR_H_MS, price=100.0)
        record_prediction(engine, pair="BTCUSDT", interval="4h",
                          model_version="m1",
                          predicted_at_ms=11 * FOUR_H_MS,
                          direction="long", confidence=0.6,
                          horizon_ms=FOUR_H_MS, price=100.0)
        body = client.get("/api/v1/chart/BTC-USDT/predictions").json()
        assert len(body["logged"]) == 2  # one per candle
        by_time = {entry["time"]: entry for entry in body["logged"]}
        # Latest prediction for candle 10 wins.
        assert by_time[10 * FOUR_H_MS // 1000]["direction"] == "flat"

    def test_model_view_series_with_predictor(self, client, engine):
        seed_candles(engine, n=120)

        class FakePredictor:
            version_id = "ensemble-test"
            feature_columns = ["rsi_14"]

            def prob_long_series(self, X):
                return [0.6] * len(X)

        app.dependency_overrides[get_predictor] = lambda: FakePredictor()
        body = client.get("/api/v1/chart/BTC-USDT/predictions").json()
        assert body["model_version"] == "ensemble-test"
        assert len(body["model_view"]) > 0
        point = body["model_view"][0]
        assert {"time", "prob_long"} <= set(point)
        assert all(0.0 <= p["prob_long"] <= 1.0 for p in body["model_view"])

    def test_no_predictor_gives_empty_model_view(self, client, engine):
        seed_candles(engine, n=120)
        body = client.get("/api/v1/chart/BTC-USDT/predictions").json()
        assert body["model_view"] == []
        assert body["model_version"] is None

    def test_training_window_end_exposed(self, client, engine, tmp_path, monkeypatch):
        """The chart needs the in-sample boundary to label the model view."""
        seed_candles(engine, n=60)
        from app.models.registry import ModelRegistry

        registry = ModelRegistry(tmp_path / "reg")
        registry.register("v1", {"directional_accuracy": 0.55},
                          ["rsi_14"], {"start": "2024-07-01T00:00:00+00:00",
                                       "end": "2026-07-01T00:00:00+00:00"})
        registry.promote("v1")
        monkeypatch.setenv("MODEL_REGISTRY_PATH", str(tmp_path / "reg"))
        body = client.get("/api/v1/chart/BTC-USDT/predictions").json()
        assert body["training_window_end"] == "2026-07-01T00:00:00+00:00"
