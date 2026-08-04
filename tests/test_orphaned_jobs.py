"""
Orphaned forecast jobs: background tasks die with the process, so any job
still pending/running when the API starts can never finish. Startup must
fail them loudly instead of leaving zombie rows that the dashboard shows as
perpetually "running" and clients poll until timeout.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import (
    AsyncSessionLocal,
    create_forecast_job,
    fail_orphaned_forecast_jobs,
    get_forecast_job,
    update_forecast_job,
)


@pytest.mark.asyncio
async def test_orphaned_pending_and_running_jobs_are_failed():
    async with AsyncSessionLocal() as db:
        # Other suite tests share this DB and may leave their own pending
        # jobs behind; flush them so the count below is deterministic.
        await fail_orphaned_forecast_jobs(db)
        await create_forecast_job(db, "orphan-pending", "AAPL", 7, "ensemble")
        await create_forecast_job(db, "orphan-running", "GOOG", 7, "ensemble")
        await update_forecast_job(db, "orphan-running", "running")
        await create_forecast_job(db, "done-job", "MSFT", 7, "ensemble")
        await update_forecast_job(db, "done-job", "completed", result_json={"predictions": []})
        await create_forecast_job(db, "failed-job", "TSLA", 7, "ensemble")
        await update_forecast_job(db, "failed-job", "failed", error_message="boom")

        count = await fail_orphaned_forecast_jobs(db)
        assert count == 2

        for job_id in ("orphan-pending", "orphan-running"):
            job = await get_forecast_job(db, job_id)
            assert job.status == "failed"
            assert "restart" in job.error_message.lower()

        assert (await get_forecast_job(db, "done-job")).status == "completed"
        failed = await get_forecast_job(db, "failed-job")
        assert failed.status == "failed"
        assert failed.error_message == "boom"


@pytest.mark.asyncio
async def test_no_orphans_is_a_noop():
    async with AsyncSessionLocal() as db:
        await fail_orphaned_forecast_jobs(db)
        assert await fail_orphaned_forecast_jobs(db) == 0


def test_startup_runs_orphan_cleanup():
    from app.main import app

    with patch("app.main.fail_orphaned_forecast_jobs", new=AsyncMock(return_value=0)) as cleanup:
        with TestClient(app):
            pass
    cleanup.assert_awaited()
