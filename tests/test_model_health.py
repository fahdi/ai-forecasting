"""
Tests for model health metrics (issue #8, PRD §4.1 R6).

Every signal is logged as a prediction; outcomes resolve once the horizon
elapses using stored klines; rolling accuracy and confidence calibration
come from resolved predictions only.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.v1.endpoints.models import get_health_engine
from app.services.kline_store import create_tables, upsert_klines
from app.services.model_health import (
    health_summary,
    record_prediction,
    resolve_predictions,
)

FOUR_H_MS = 4 * 3_600_000


@pytest.fixture
def engine():
    # StaticPool + check_same_thread=False: the endpoint under TestClient
    # touches the engine from another thread; in-memory SQLite must share
    # one connection or the endpoint sees an empty database.
    eng = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    create_tables(eng)
    return eng


def add_candle(engine, pair, open_time_ms, close):
    upsert_klines(engine, [{
        "pair": pair, "interval": "4h", "open_time_ms": open_time_ms,
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": 10.0,
    }])


def now_at(ms):
    return pd.Timestamp(ms, unit="ms", tz="UTC")


class TestResolution:
    def test_long_prediction_resolves_win_when_price_rises(self, engine):
        record_prediction(engine, pair="BTCUSDT", interval="4h",
                          model_version="m1", predicted_at_ms=0,
                          direction="long", confidence=0.7,
                          horizon_ms=FOUR_H_MS, price=100.0)
        add_candle(engine, "BTCUSDT", FOUR_H_MS, close=105.0)
        resolved = resolve_predictions(engine, now=now_at(2 * FOUR_H_MS))
        assert resolved == 1
        summary = health_summary(engine, now=now_at(2 * FOUR_H_MS))
        pair_stats = summary["pairs"][0]
        assert pair_stats["pair"] == "BTC/USDT"
        assert pair_stats["directional_accuracy_7d"] == 1.0

    def test_flat_prediction_correct_when_price_falls(self, engine):
        record_prediction(engine, pair="BTCUSDT", interval="4h",
                          model_version="m1", predicted_at_ms=0,
                          direction="flat", confidence=0.8,
                          horizon_ms=FOUR_H_MS, price=100.0)
        add_candle(engine, "BTCUSDT", FOUR_H_MS, close=95.0)
        resolve_predictions(engine, now=now_at(2 * FOUR_H_MS))
        summary = health_summary(engine, now=now_at(2 * FOUR_H_MS))
        assert summary["pairs"][0]["directional_accuracy_7d"] == 1.0

    def test_not_resolved_before_horizon(self, engine):
        record_prediction(engine, pair="BTCUSDT", interval="4h",
                          model_version="m1", predicted_at_ms=0,
                          direction="long", confidence=0.7,
                          horizon_ms=FOUR_H_MS, price=100.0)
        assert resolve_predictions(engine, now=now_at(FOUR_H_MS // 2)) == 0
        summary = health_summary(engine, now=now_at(FOUR_H_MS // 2))
        assert summary["pairs"][0]["directional_accuracy_7d"] is None
        assert summary["pairs"][0]["n_predictions"] == 1

    def test_unresolvable_without_candle_stays_pending(self, engine):
        record_prediction(engine, pair="BTCUSDT", interval="4h",
                          model_version="m1", predicted_at_ms=0,
                          direction="long", confidence=0.7,
                          horizon_ms=FOUR_H_MS, price=100.0)
        assert resolve_predictions(engine, now=now_at(3 * FOUR_H_MS)) == 0


class TestWindows:
    def test_old_predictions_excluded_from_7d_window(self, engine):
        day_ms = 24 * 3_600_000
        # Wrong prediction 10 days ago; correct one today.
        record_prediction(engine, pair="BTCUSDT", interval="4h",
                          model_version="m1", predicted_at_ms=0,
                          direction="long", confidence=0.7,
                          horizon_ms=FOUR_H_MS, price=100.0)
        add_candle(engine, "BTCUSDT", FOUR_H_MS, close=90.0)  # long loses
        recent = 10 * day_ms
        record_prediction(engine, pair="BTCUSDT", interval="4h",
                          model_version="m1", predicted_at_ms=recent,
                          direction="long", confidence=0.7,
                          horizon_ms=FOUR_H_MS, price=100.0)
        add_candle(engine, "BTCUSDT", recent + FOUR_H_MS, close=110.0)  # wins
        now = now_at(recent + 2 * FOUR_H_MS)
        resolve_predictions(engine, now=now)
        stats = health_summary(engine, now=now)["pairs"][0]
        assert stats["directional_accuracy_7d"] == 1.0
        assert stats["directional_accuracy_30d"] == 0.5

    def test_calibration_buckets_present(self, engine):
        for i, (conf, close_after) in enumerate(
            [(0.55, 110.0), (0.65, 90.0), (0.85, 110.0), (0.95, 110.0)]
        ):
            t = i * 10 * FOUR_H_MS
            record_prediction(engine, pair="BTCUSDT", interval="4h",
                              model_version="m1", predicted_at_ms=t,
                              direction="long", confidence=conf,
                              horizon_ms=FOUR_H_MS, price=100.0)
            add_candle(engine, "BTCUSDT", t + FOUR_H_MS, close=close_after)
        now = now_at(40 * FOUR_H_MS)
        resolve_predictions(engine, now=now)
        calibration = health_summary(engine, now=now)["pairs"][0]["calibration"]
        assert calibration, "expected non-empty calibration buckets"
        for bucket in calibration:
            assert set(bucket) == {"bucket_low", "bucket_high", "predicted_mean",
                                   "realized_hit_rate", "count"}
        assert sum(b["count"] for b in calibration) == 4


class TestSignalRecording:
    def test_every_served_signal_is_logged(self, engine):
        """R6: prediction-vs-actual history persisted for every signal."""
        from sqlalchemy import select

        from app.services.model_health import prediction_log
        from tests.test_signal_endpoint import FakeCandleSource
        from app.services.signal_service import get_candle_source, get_predictor

        app.dependency_overrides[get_candle_source] = lambda: FakeCandleSource()
        app.dependency_overrides[get_predictor] = lambda: None
        app.dependency_overrides[get_health_engine] = lambda: engine
        client = TestClient(app)
        body = client.get("/api/v1/signal/BTC-USDT").json()
        app.dependency_overrides.clear()

        with engine.connect() as conn:
            rows = conn.execute(select(prediction_log)).mappings().all()
        assert len(rows) == 1
        row = rows[0]
        assert row["pair"] == "BTCUSDT"
        assert row["direction"] == body["direction"]
        assert row["model_version"] == body["model_version"]
        assert row["price"] > 0


class TestEndpoint:
    def test_health_endpoint_contract(self, engine):
        record_prediction(engine, pair="ETHUSDT", interval="4h",
                          model_version="m1", predicted_at_ms=0,
                          direction="long", confidence=0.7,
                          horizon_ms=FOUR_H_MS, price=100.0)
        app.dependency_overrides[get_health_engine] = lambda: engine
        client = TestClient(app)
        response = client.get("/api/v1/models/health")
        app.dependency_overrides.clear()
        assert response.status_code == 200
        body = response.json()
        assert "pairs" in body
        entry = body["pairs"][0]
        assert {"pair", "directional_accuracy_7d", "directional_accuracy_30d",
                "n_predictions", "calibration"} <= set(entry)
