"""
Coverage tests for app/api/v1/endpoints/forecast.py

The async get_db dependency is overridden with a mock session and the
database helpers (create_forecast_job / get_forecast_job / update_forecast_job)
are patched in the endpoint namespace, so no live database is needed.
Background task functions are exercised by awaiting them directly.

The blanket-except bugs previously pinned here (/batch and /results
re-raising intentional 400/404s as 500) were fixed as part of making the
forecast pipeline real; these tests now assert the intended status codes.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.api.v1.endpoints.forecast import (
    process_batch_forecast,
    process_single_forecast,
)

client = TestClient(app)

NS = "app.api.v1.endpoints.forecast"


@pytest.fixture(autouse=True)
def mock_db():
    async def _get_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)


def make_session_factory() -> MagicMock:
    """Stand-in for AsyncSessionLocal: factory whose product is an async CM."""
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    session_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session_cm)


def make_job(**overrides) -> SimpleNamespace:
    job = SimpleNamespace(
        job_id="job-1",
        status="running",
        symbol="AAPL",
        forecast_horizon=7,
        model_type="ensemble",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        completed_at=None,
        error_message=None,
        result_path=None,
        result_json=None,
        metadata={"include_confidence": True},
    )
    for key, value in overrides.items():
        setattr(job, key, value)
    return job


class TestSingleForecast:
    def test_create_single_forecast_success(self):
        with patch(f"{NS}.create_forecast_job", new=AsyncMock()) as create_job, \
             patch(f"{NS}.process_single_forecast", new=AsyncMock()) as bg_task:
            response = client.post(
                "/api/v1/forecast/single",
                json={"symbol": "aapl", "forecast_horizon": 14,
                      "model_type": "xgboost"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["message"] == "Forecast job created successfully"
        assert body["estimated_completion"] is not None
        assert create_job.await_args.kwargs["symbol"] == "AAPL"
        assert create_job.await_args.kwargs["forecast_horizon"] == 14
        # TestClient executes background tasks before returning the response.
        assert bg_task.await_count == 1
        assert bg_task.await_args.kwargs["symbol"] == "AAPL"
        assert bg_task.await_args.kwargs["job_id"] == body["job_id"]

    @pytest.mark.parametrize("horizon", [0, 5000])
    def test_create_single_forecast_horizon_validation(self, horizon):
        response = client.post(
            "/api/v1/forecast/single",
            json={"symbol": "AAPL", "forecast_horizon": horizon},
        )
        assert response.status_code == 422

    def test_create_single_forecast_db_error_returns_500(self):
        with patch(f"{NS}.create_forecast_job",
                   new=AsyncMock(side_effect=RuntimeError("db down"))):
            response = client.post(
                "/api/v1/forecast/single", json={"symbol": "AAPL"}
            )
        assert response.status_code == 500
        assert "db down" in response.json()["detail"]


class TestBatchForecast:
    def test_create_batch_forecast_success(self):
        with patch(f"{NS}.create_forecast_job", new=AsyncMock()) as create_job, \
             patch(f"{NS}.process_batch_forecast", new=AsyncMock()) as bg_task:
            response = client.post(
                "/api/v1/forecast/batch",
                json={"symbols": ["AAPL", "GOOGL"], "forecast_horizon": 7},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert "2 symbols" in body["message"]
        assert create_job.await_args.kwargs["symbol"] == "AAPL,GOOGL"
        assert bg_task.await_count == 1
        assert bg_task.await_args.kwargs["symbols"] == ["AAPL", "GOOGL"]

    def test_create_batch_forecast_too_many_symbols(self):
        symbols = [f"S{i}" for i in range(101)]
        with patch(f"{NS}.create_forecast_job", new=AsyncMock()):
            response = client.post(
                "/api/v1/forecast/batch", json={"symbols": symbols}
            )
        assert response.status_code == 400
        assert "Maximum 100 symbols" in response.json()["detail"]

    def test_create_batch_forecast_db_error_returns_500(self):
        with patch(f"{NS}.create_forecast_job",
                   new=AsyncMock(side_effect=RuntimeError("insert failed"))):
            response = client.post(
                "/api/v1/forecast/batch", json={"symbols": ["AAPL"]}
            )
        assert response.status_code == 500
        assert "insert failed" in response.json()["detail"]


class TestForecastStatus:
    def test_status_found(self):
        job = make_job()
        with patch(f"{NS}.get_forecast_job", new=AsyncMock(return_value=job)):
            response = client.get("/api/v1/forecast/status/job-1")
        assert response.status_code == 200
        body = response.json()
        assert body["job_id"] == "job-1"
        assert body["status"] == "running"
        assert body["symbol"] == "AAPL"
        assert body["forecast_horizon"] == 7
        assert body["error_message"] is None

    def test_status_not_found_is_404(self):
        with patch(f"{NS}.get_forecast_job", new=AsyncMock(return_value=None)):
            response = client.get("/api/v1/forecast/status/missing")
        assert response.status_code == 404
        assert response.json()["detail"] == "Job not found"

    def test_status_db_error_returns_500(self):
        with patch(f"{NS}.get_forecast_job",
                   new=AsyncMock(side_effect=RuntimeError("query failed"))):
            response = client.get("/api/v1/forecast/status/job-1")
        assert response.status_code == 500
        assert "query failed" in response.json()["detail"]


class TestForecastResults:
    def test_results_completed(self):
        job = make_job(status="completed", result_path="results/job-1.json",
                       result_json={
                           "metadata": {"symbol": "AAPL"},
                           "predictions": [{"date": "2026-01-02", "value": 190.0}],
                           "performance_metrics": {"mape": 1.5},
                       })
        with patch(f"{NS}.get_forecast_job", new=AsyncMock(return_value=job)):
            response = client.get("/api/v1/forecast/results/job-1")
        assert response.status_code == 200
        body = response.json()
        assert body["job_id"] == "job-1"
        assert body["status"] == "completed"
        assert body["predictions"] == [{"date": "2026-01-02", "value": 190.0}]
        assert body["metadata"] == {"symbol": "AAPL"}

    def test_results_not_found(self):
        with patch(f"{NS}.get_forecast_job", new=AsyncMock(return_value=None)):
            response = client.get("/api/v1/forecast/results/missing")
        assert response.status_code == 404
        assert "Job not found" in response.json()["detail"]

    def test_results_job_not_completed(self):
        job = make_job(status="running")
        with patch(f"{NS}.get_forecast_job", new=AsyncMock(return_value=job)):
            response = client.get("/api/v1/forecast/results/job-1")
        assert response.status_code == 400
        assert "Job status is running, not completed" in response.json()["detail"]


class TestProcessSingleForecast:
    @pytest.mark.asyncio
    async def test_success_marks_completed(self):
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        with patch("app.core.database.AsyncSessionLocal", make_session_factory()), \
             patch(f"{NS}.update_forecast_job", new=AsyncMock()) as update_job, \
             patch(f"{NS}.DataService") as ds, \
             patch(f"{NS}.ForecastService") as fs:
            ds.return_value.get_historical_data = AsyncMock(return_value=df)
            fs.return_value.forecast = AsyncMock(
                return_value={"predictions": [{"day": 1, "value": 3.1}]}
            )
            await process_single_forecast(
                job_id="job-1", symbol="AAPL", forecast_horizon=7,
                model_type="ensemble", include_confidence=True,
                include_features=False,
            )
        statuses = [call.args[2] for call in update_job.await_args_list]
        assert statuses == ["running", "completed"]
        assert update_job.await_args_list[1].kwargs["result_path"] == "results/job-1.json"
        fs.return_value.forecast.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_data_marks_failed(self):
        with patch("app.core.database.AsyncSessionLocal", make_session_factory()), \
             patch(f"{NS}.update_forecast_job", new=AsyncMock()) as update_job, \
             patch(f"{NS}.DataService") as ds, \
             patch(f"{NS}.ForecastService"):
            ds.return_value.get_historical_data = AsyncMock(
                return_value=pd.DataFrame()
            )
            await process_single_forecast(
                job_id="job-2", symbol="NOPE", forecast_horizon=7,
                model_type="ensemble", include_confidence=True,
                include_features=False,
            )
        statuses = [call.args[2] for call in update_job.await_args_list]
        assert statuses == ["running", "failed"]
        assert "No historical data available for NOPE" in (
            update_job.await_args_list[1].kwargs["error_message"]
        )


class TestProcessBatchForecast:
    @pytest.mark.asyncio
    async def test_mixed_symbols_still_completes(self):
        """Empty data is skipped, per-symbol failures are swallowed, and the
        job still finishes as completed."""
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})

        async def fetch(symbol):
            if symbol == "EMPTY":
                return pd.DataFrame()
            if symbol == "BAD":
                raise RuntimeError("fetch exploded")
            return df

        with patch("app.core.database.AsyncSessionLocal", make_session_factory()), \
             patch(f"{NS}.update_forecast_job", new=AsyncMock()) as update_job, \
             patch(f"{NS}.DataService") as ds, \
             patch(f"{NS}.ForecastService") as fs:
            ds.return_value.get_historical_data = AsyncMock(side_effect=fetch)
            fs.return_value.forecast = AsyncMock(return_value={"predictions": []})
            await process_batch_forecast(
                job_id="job-3", symbols=["EMPTY", "GOOD", "BAD"],
                forecast_horizon=7, model_type="ensemble",
                include_confidence=True, include_features=False,
            )
        statuses = [call.args[2] for call in update_job.await_args_list]
        assert statuses == ["running", "completed"]
        # Only the symbol with data reached the forecaster.
        fs.return_value.forecast.assert_awaited_once()
        assert fs.return_value.forecast.await_args.kwargs["symbol"] == "GOOD"

    @pytest.mark.asyncio
    async def test_outer_failure_marks_failed(self):
        update_job = AsyncMock(side_effect=[RuntimeError("db gone"), None])
        with patch("app.core.database.AsyncSessionLocal", make_session_factory()), \
             patch(f"{NS}.update_forecast_job", new=update_job), \
             patch(f"{NS}.DataService"), patch(f"{NS}.ForecastService"):
            await process_batch_forecast(
                job_id="job-4", symbols=["AAPL"], forecast_horizon=7,
                model_type="ensemble", include_confidence=True,
                include_features=False,
            )
        assert update_job.await_count == 2
        final = update_job.await_args_list[1]
        assert final.args[2] == "failed"
        assert "db gone" in final.kwargs["error_message"]
