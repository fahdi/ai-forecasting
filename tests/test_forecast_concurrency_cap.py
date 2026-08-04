"""
Concurrency cap on forecast creation. Each forecast trains models (~30s of
multi-core CPU) on a VPS shared with other production sites, so unbounded
job creation could saturate the box. At the cap, creation returns 429 with
a clear retry message instead of quietly queueing more work.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db

client = TestClient(app)
NS = "app.api.v1.endpoints.forecast"


@pytest.fixture(autouse=True)
def _db_override():
    async def _get_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)


def test_single_rejected_at_cap_with_429():
    with patch(f"{NS}.count_active_forecast_jobs", new=AsyncMock(return_value=3)), \
         patch(f"{NS}.create_forecast_job", new=AsyncMock()) as create_job:
        response = client.post("/api/v1/forecast/single", json={"symbol": "AAPL"})
    assert response.status_code == 429
    assert "try again" in response.json()["detail"].lower()
    create_job.assert_not_awaited()


def test_single_allowed_under_cap():
    with patch(f"{NS}.count_active_forecast_jobs", new=AsyncMock(return_value=2)), \
         patch(f"{NS}.create_forecast_job", new=AsyncMock()), \
         patch(f"{NS}.process_single_forecast", new=AsyncMock()):
        response = client.post("/api/v1/forecast/single", json={"symbol": "AAPL"})
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_batch_rejected_at_cap_with_429():
    with patch(f"{NS}.count_active_forecast_jobs", new=AsyncMock(return_value=3)), \
         patch(f"{NS}.create_forecast_job", new=AsyncMock()) as create_job:
        response = client.post("/api/v1/forecast/batch", json={"symbols": ["AAPL", "GOOG"]})
    assert response.status_code == 429
    create_job.assert_not_awaited()


def test_single_intended_http_errors_are_not_wrapped_as_500():
    """The /single blanket except previously converted any HTTPException
    raised inside the handler into a 500 (same bug family as /batch and
    /results, fixed earlier)."""
    with patch(f"{NS}.count_active_forecast_jobs", new=AsyncMock(return_value=99)):
        response = client.post("/api/v1/forecast/single", json={"symbol": "AAPL"})
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_forecast_training_does_not_block_event_loop():
    """CPU-bound training used to run on the event loop, freezing every
    request (dashboard polling, health checks) for the duration and
    serializing jobs so the concurrency cap could never engage."""
    import asyncio
    import time

    import pandas as pd

    from app.api.v1.endpoints.forecast import process_single_forecast

    frame = pd.DataFrame({"Close": [1.0, 2.0]})

    class SlowDataService:
        async def get_historical_data(self, symbol):
            time.sleep(1.0)  # blocking work; must land on a worker thread
            return frame

    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{NS}.DataService", SlowDataService), \
         patch(f"{NS}.ForecastService") as forecast_service_cls, \
         patch(f"{NS}.update_forecast_job", new=AsyncMock()), \
         patch("app.core.database.AsyncSessionLocal", session_factory):
        forecast_service_cls.return_value.forecast = AsyncMock(
            return_value={"metadata": {}, "predictions": []}
        )
        task = asyncio.create_task(
            process_single_forecast(
                job_id="loop-block-test",
                symbol="AAPL",
                forecast_horizon=7,
                model_type="ensemble",
                include_confidence=True,
                include_features=False,
            )
        )
        # The task starts on the first await. If its blocking work runs on
        # the event loop, this 0.1s sleep will not return for ~1s.
        t0 = time.perf_counter()
        await asyncio.sleep(0.1)
        loop_latency = time.perf_counter() - t0 - 0.1
        await task

    assert loop_latency < 0.4, (
        f"event loop was blocked for {loop_latency:.2f}s during training"
    )
