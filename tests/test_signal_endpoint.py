"""
Tests for GET /api/v1/signal/{pair} (issue #7, PRD §4.1 R3).

The endpoint serves trade signals from the active model over candles supplied
by an injectable CandleSource — tests inject a fake source, no network.
"""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.signal_service import get_candle_source


class FakeCandleSource:
    def __init__(self, trend: str = "up", bars: int = 120, stale_hours: float = 0.0):
        self.trend = trend
        self.bars = bars
        self.stale_hours = stale_hours

    def get_recent_candles(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        n = min(self.bars, limit)
        rng = np.random.default_rng(42)
        drift = {"up": 0.004, "down": -0.004}[self.trend]
        close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.001, n)))
        end = pd.Timestamp.now(tz="UTC").floor("4h") - pd.Timedelta(
            hours=self.stale_hours
        )
        open_time = pd.date_range(end=end, periods=n, freq="4h")
        return pd.DataFrame(
            {
                "open_time": open_time,
                "open": close,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": rng.uniform(100, 1000, n),
            }
        )


@pytest.fixture
def client():
    # No context manager: skips app lifespan (DB init) — the signal endpoint
    # has no database dependency, matching tests/test_basic.py.
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


def use_source(source: FakeCandleSource):
    app.dependency_overrides[get_candle_source] = lambda: source


class TestContract:
    def test_happy_path_schema(self, client):
        use_source(FakeCandleSource(trend="up"))
        response = client.get("/api/v1/signal/BTC-USDT")
        assert response.status_code == 200
        body = response.json()
        assert body["pair"] == "BTC/USDT"
        assert body["direction"] in ("long", "flat")
        assert 0.0 <= body["confidence"] <= 1.0
        assert body["horizon"] == "4h"
        assert isinstance(body["model_votes"], dict) and body["model_votes"]
        assert isinstance(body["top_features"], list) and body["top_features"]
        assert body["model_version"]
        assert body["generated_at"]
        assert body["stale"] is False

    def test_pair_format_variants_normalize(self, client):
        use_source(FakeCandleSource(trend="up"))
        for path in ("BTC-USDT", "BTC/USDT", "btcusdt", "btc_usdt"):
            response = client.get(f"/api/v1/signal/{path}")
            assert response.status_code == 200, path
            assert response.json()["pair"] == "BTC/USDT"

    def test_unknown_pair_404(self, client):
        use_source(FakeCandleSource(trend="up"))
        response = client.get("/api/v1/signal/DOGE-USDT")
        assert response.status_code == 404
        assert "DOGE" in response.json()["detail"]

    def test_malformed_pair_404(self, client):
        use_source(FakeCandleSource(trend="up"))
        assert client.get("/api/v1/signal/not!!a@pair").status_code == 404


class TestSignalLogic:
    def test_uptrend_gives_long(self, client):
        use_source(FakeCandleSource(trend="up"))
        body = client.get("/api/v1/signal/ETH-USDT").json()
        assert body["direction"] == "long"

    def test_downtrend_gives_flat_never_short(self, client):
        use_source(FakeCandleSource(trend="down"))
        body = client.get("/api/v1/signal/ETH-USDT").json()
        assert body["direction"] == "flat"  # spot-only: long or flat, never short

    def test_stale_data_flagged(self, client):
        # Last candle closed more than 2 intervals (8h) ago -> stale=True (R9).
        use_source(FakeCandleSource(trend="up", stale_hours=16.0))
        body = client.get("/api/v1/signal/BTC-USDT").json()
        assert body["stale"] is True

    def test_insufficient_history_503(self, client):
        use_source(FakeCandleSource(trend="up", bars=20))
        response = client.get("/api/v1/signal/BTC-USDT")
        assert response.status_code == 503
        assert "insufficient" in response.json()["detail"].lower()
