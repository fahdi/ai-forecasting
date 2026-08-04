"""
Forecast reuse: creating a forecast for the same symbol/horizon/model while
a fresh completed result exists returns that job immediately instead of
retraining (~30s of shared-VPS CPU) and burning the concurrency cap.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import (
    AsyncSessionLocal,
    create_forecast_job,
    find_reusable_forecast_job,
    update_forecast_job,
)
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


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_helper_finds_fresh_completed_job_with_results():
    async with AsyncSessionLocal() as db:
        await create_forecast_job(db, "reuse-hit", "REUSE1", 7, "ensemble")
        await update_forecast_job(
            db, "reuse-hit", "completed",
            result_json={"predictions": [{"predicted_price": 1.0}]},
        )
        job = await find_reusable_forecast_job(db, "REUSE1", 7, "ensemble", max_age_minutes=60)
        assert job is not None and job.job_id == "reuse-hit"


@pytest.mark.asyncio
async def test_helper_ignores_wrong_params_failed_and_resultless_jobs():
    async with AsyncSessionLocal() as db:
        await create_forecast_job(db, "reuse-fail", "REUSE2", 7, "ensemble")
        await update_forecast_job(db, "reuse-fail", "failed", error_message="x")
        await create_forecast_job(db, "reuse-noresult", "REUSE2", 7, "ensemble")
        await update_forecast_job(db, "reuse-noresult", "completed")  # no result_json
        assert await find_reusable_forecast_job(db, "REUSE2", 7, "ensemble", max_age_minutes=60) is None
        # Same symbol, different horizon/model must not match
        await create_forecast_job(db, "reuse-h30", "REUSE2", 30, "ensemble")
        await update_forecast_job(db, "reuse-h30", "completed", result_json={"predictions": []})
        assert await find_reusable_forecast_job(db, "REUSE2", 7, "ensemble", max_age_minutes=60) is None
        assert await find_reusable_forecast_job(db, "REUSE2", 30, "xgboost", max_age_minutes=60) is None


@pytest.mark.asyncio
async def test_helper_ignores_stale_jobs():
    async with AsyncSessionLocal() as db:
        await create_forecast_job(db, "reuse-old", "REUSE3", 7, "ensemble")
        job = await update_forecast_job(
            db, "reuse-old", "completed", result_json={"predictions": []}
        )
        job.completed_at = datetime.utcnow() - timedelta(minutes=90)
        await db.commit()
        assert await find_reusable_forecast_job(db, "REUSE3", 7, "ensemble", max_age_minutes=60) is None


# ---------------------------------------------------------------------------
# Endpoint behavior
# ---------------------------------------------------------------------------

def _reusable_job():
    return SimpleNamespace(
        job_id="existing-job",
        status="completed",
        completed_at=datetime.utcnow() - timedelta(minutes=5),
    )


def test_single_reuses_fresh_result_without_creating_a_job():
    with patch(f"{NS}.find_reusable_forecast_job", new=AsyncMock(return_value=_reusable_job())), \
         patch(f"{NS}.count_active_forecast_jobs", new=AsyncMock(return_value=0)), \
         patch(f"{NS}.create_forecast_job", new=AsyncMock()) as create_job:
        response = client.post("/api/v1/forecast/single", json={"symbol": "AAPL"})
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "existing-job"
    assert body["status"] == "completed"
    assert "reus" in body["message"].lower()
    create_job.assert_not_awaited()


def test_single_reuse_beats_the_concurrency_cap():
    """A reusable result must be served even when the cap would reject new work."""
    with patch(f"{NS}.find_reusable_forecast_job", new=AsyncMock(return_value=_reusable_job())), \
         patch(f"{NS}.count_active_forecast_jobs", new=AsyncMock(return_value=99)):
        response = client.post("/api/v1/forecast/single", json={"symbol": "AAPL"})
    assert response.status_code == 200
    assert response.json()["job_id"] == "existing-job"


def test_single_creates_new_job_when_nothing_reusable():
    with patch(f"{NS}.find_reusable_forecast_job", new=AsyncMock(return_value=None)), \
         patch(f"{NS}.count_active_forecast_jobs", new=AsyncMock(return_value=0)), \
         patch(f"{NS}.create_forecast_job", new=AsyncMock()) as create_job, \
         patch(f"{NS}.process_single_forecast", new=AsyncMock()):
        response = client.post("/api/v1/forecast/single", json={"symbol": "AAPL"})
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    create_job.assert_awaited_once()
