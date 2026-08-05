"""
Market data freshness for /health/detailed (app.services.market_data_status).

On 2026-08-03 Binance began answering this VPS with HTTP 451 (restricted
location). The kline ingestor and freqtrade both died, and /health/detailed
went on reporting "healthy" for 32 hours because it only checked the database,
redis, disk, model dir, ML imports and backups. Nothing asked the question the
product actually depends on: is market data still arriving?

Freshness is judged from the newest kline the ingestor persisted, so it also
catches an ingestor that is running but no longer ingesting.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.market_data_status import (
    INTERVAL_SECONDS,
    STALE_AFTER_INTERVALS,
    market_data_status,
)

NOW = datetime(2026, 8, 5, 12, 0, 0)


def _ms(dt: datetime) -> int:
    """Kline open_time_ms is a UTC epoch; NOW is naive UTC, not local time."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_recent_kline_is_healthy():
    status = market_data_status(_ms(NOW - timedelta(hours=1)), interval="4h", now=NOW)
    assert status["status"] == "healthy"
    assert status["age_hours"] == pytest.approx(1.0, abs=0.01)
    assert status["interval"] == "4h"


def test_missed_candles_are_stale():
    """The real outage: last kline 32 hours old on a 4h feed."""
    status = market_data_status(_ms(NOW - timedelta(hours=32)), interval="4h", now=NOW)
    assert status["status"] == "stale"
    assert status["age_hours"] == pytest.approx(32.0, abs=0.01)
    assert "32" in status["message"]


def test_no_klines_at_all_is_missing():
    status = market_data_status(None, interval="4h", now=NOW)
    assert status["status"] == "missing"
    assert status["newest_kline"] is None


def test_threshold_tracks_the_interval():
    """A 12-hour-old bar is fine on a daily feed and stale on a 4h feed."""
    twelve_h = _ms(NOW - timedelta(hours=12))
    assert market_data_status(twelve_h, interval="1d", now=NOW)["status"] == "healthy"
    assert market_data_status(twelve_h, interval="4h", now=NOW)["status"] == "stale"


@pytest.mark.parametrize("interval", sorted(INTERVAL_SECONDS))
def test_boundary_is_consistent_for_every_supported_interval(interval):
    window = INTERVAL_SECONDS[interval] * STALE_AFTER_INTERVALS
    just_inside = _ms(NOW - timedelta(seconds=window - 60))
    just_outside = _ms(NOW - timedelta(seconds=window + 60))
    assert market_data_status(just_inside, interval=interval, now=NOW)["status"] == "healthy"
    assert market_data_status(just_outside, interval=interval, now=NOW)["status"] == "stale"


def test_unknown_interval_does_not_explode():
    """An unrecognised interval must not take the health endpoint down."""
    status = market_data_status(_ms(NOW), interval="7m", now=NOW)
    assert status["status"] in {"healthy", "unknown"}


def test_future_timestamps_do_not_read_as_stale():
    """Clock skew between the ingestor host and the API must not page anyone."""
    status = market_data_status(_ms(NOW + timedelta(minutes=5)), interval="4h", now=NOW)
    assert status["status"] == "healthy"
    assert status["age_hours"] >= 0


def test_reports_iso_timestamp_for_the_newest_bar():
    newest = NOW - timedelta(hours=2)
    status = market_data_status(_ms(newest), interval="4h", now=NOW)
    assert status["newest_kline"].startswith("2026-08-05T10:00")


class TestWiredIntoHealthEndpoint:
    """The component only matters if /health/detailed stops saying "healthy"."""

    def test_stale_feed_degrades_the_endpoint(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastapi.testclient import TestClient

        from app.core.database import get_db
        from app.main import app

        stale_ms = _ms(datetime.utcnow() - timedelta(hours=32))
        result = MagicMock()
        result.fetchone = AsyncMock(return_value=(1,))
        result.scalar = MagicMock(return_value=stale_ms)
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)

        async def _override():
            yield session

        app.dependency_overrides[get_db] = _override
        try:
            redis_mod = MagicMock()
            client_mock = MagicMock()
            client_mock.ping = AsyncMock(return_value=True)
            client_mock.close = AsyncMock()
            redis_mod.from_url.return_value = client_mock
            with patch("app.api.v1.endpoints.health.redis", redis_mod):
                body = TestClient(app).get("/api/v1/health/detailed").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert body["components"]["market_data"]["status"] == "stale"
        assert body["status"] == "degraded"

    def test_undeterminable_freshness_is_not_reported_as_healthy(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastapi.testclient import TestClient

        from app.core.database import get_db
        from app.main import app

        # First execute() is the database SELECT 1 probe; the klines query
        # then fails the way a missing table or driver error would.
        result = MagicMock()
        result.fetchone = AsyncMock(return_value=(1,))
        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=[result, RuntimeError('relation "klines" does not exist')]
        )

        async def _override():
            yield session

        app.dependency_overrides[get_db] = _override
        try:
            redis_mod = MagicMock()
            client_mock = MagicMock()
            client_mock.ping = AsyncMock(return_value=True)
            client_mock.close = AsyncMock()
            redis_mod.from_url.return_value = client_mock
            with patch("app.api.v1.endpoints.health.redis", redis_mod):
                body = TestClient(app).get("/api/v1/health/detailed").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert body["components"]["market_data"]["status"] == "unknown"
