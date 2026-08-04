"""
TDD for making the legacy forecast pipeline real (multi-asset forecasting):

- Friendly symbol aliases (XAU -> GC=F, GOLD -> GC=F, BTC -> BTC-USD, ...)
  so what a user types in the dashboard maps to a real Yahoo Finance ticker.
- Forecast results are persisted (ForecastJob.result_json) instead of being
  discarded, and GET /results/{job_id} serves the stored predictions.
- /results raises proper 404/400 instead of wrapping them into 500s.
- GET /api/v1/forecast/recent lists recent jobs (with a compact prediction
  summary) so the dashboard can show real recent forecasts.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.services.data_service import DataService, normalize_symbol
from app.api.v1.endpoints.forecast import process_single_forecast

client = TestClient(app)
NS = "app.api.v1.endpoints.forecast"


def override_db():
    async def _get_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _get_db


def clear_db_override():
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _db_override():
    override_db()
    yield
    clear_db_override()


def make_job(**overrides) -> SimpleNamespace:
    base = dict(
        job_id="job-1",
        status="completed",
        symbol="GC=F",
        forecast_horizon=7,
        model_type="ensemble",
        created_at=datetime(2026, 8, 4, 12, 0, 0),
        updated_at=datetime(2026, 8, 4, 12, 1, 0),
        completed_at=datetime(2026, 8, 4, 12, 1, 0),
        error_message=None,
        result_path="results/job-1.json",
        result_json={
            "metadata": {"symbol": "GC=F", "model_used": "ensemble", "horizon": 7},
            "predictions": [{"date": "2026-08-05", "value": 2500.0}],
            "performance_metrics": {"mape": 1.2},
        },
        job_metadata={"include_confidence": True},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Symbol aliases
# ---------------------------------------------------------------------------

class TestSymbolAliases:
    @pytest.mark.parametrize(
        "friendly,expected",
        [
            ("XAU", "GC=F"),
            ("GOLD", "GC=F"),
            ("XAG", "SI=F"),
            ("SILVER", "SI=F"),
            ("OIL", "CL=F"),
            ("WTI", "CL=F"),
            ("BRENT", "BZ=F"),
            ("BTC", "BTC-USD"),
            ("ETH", "ETH-USD"),
            ("SPX", "^GSPC"),
            ("NDX", "^NDX"),
        ],
    )
    def test_friendly_aliases_map_to_yahoo_tickers(self, friendly, expected):
        assert normalize_symbol(friendly) == expected

    def test_lowercase_and_whitespace_normalized(self):
        assert normalize_symbol("  xau ") == "GC=F"

    @pytest.mark.parametrize(
        "pair,expected",
        [
            ("XAU/USD", "GC=F"),
            ("XAUUSD", "GC=F"),
            ("XAG/USD", "SI=F"),
            ("BTC/USD", "BTC-USD"),
            ("ETHUSD", "ETH-USD"),
        ],
    )
    def test_usd_pair_spellings_map_to_base_alias(self, pair, expected):
        assert normalize_symbol(pair) == expected

    def test_unknown_usd_pair_passes_through(self):
        assert normalize_symbol("FOO/USD") == "FOO/USD"

    def test_plain_tickers_pass_through_uppercased(self):
        assert normalize_symbol("aapl") == "AAPL"
        assert normalize_symbol("GC=F") == "GC=F"

    @pytest.mark.asyncio
    async def test_get_historical_data_fetches_normalized_symbol(self):
        service = DataService()
        frame = pd.DataFrame({"Close": [1.0]})
        with patch.object(service, "_load_cached_data", new=AsyncMock(return_value=None)), \
             patch.object(service, "_fetch_yahoo_data", new=AsyncMock(return_value=frame)) as fetch, \
             patch.object(service, "_cache_data", new=AsyncMock()):
            await service.get_historical_data("XAU")
        assert fetch.await_args.args[0] == "GC=F"


# ---------------------------------------------------------------------------
# Result persistence
# ---------------------------------------------------------------------------

class TestResultPersistence:
    @pytest.mark.asyncio
    async def test_process_single_forecast_persists_result_json(self):
        forecast_payload = {
            "metadata": {"symbol": "GC=F"},
            "predictions": [{"date": "2026-08-05", "value": 2500.0}],
            "performance_metrics": {"mape": 1.0},
        }
        frame = pd.DataFrame({"Close": [1.0, 2.0]})
        update = AsyncMock()
        session_factory = MagicMock()
        session_factory.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{NS}.update_forecast_job", new=update), \
             patch("app.core.database.AsyncSessionLocal", session_factory), \
             patch(f"{NS}.DataService") as data_service_cls, \
             patch(f"{NS}.ForecastService") as forecast_service_cls:
            data_service_cls.return_value.get_historical_data = AsyncMock(return_value=frame)
            forecast_service_cls.return_value.forecast = AsyncMock(return_value=forecast_payload)
            await process_single_forecast(
                job_id="job-1",
                symbol="XAU",
                forecast_horizon=7,
                model_type="ensemble",
                include_confidence=True,
                include_features=False,
            )

        completed_call = [c for c in update.await_args_list if "completed" in c.args][-1]
        assert completed_call.kwargs["result_json"] == forecast_payload


# ---------------------------------------------------------------------------
# /results endpoint
# ---------------------------------------------------------------------------

class TestResultsEndpoint:
    def test_results_returns_stored_predictions(self):
        with patch(f"{NS}.get_forecast_job", new=AsyncMock(return_value=make_job())):
            response = client.get("/api/v1/forecast/results/job-1")
        assert response.status_code == 200
        body = response.json()
        assert body["predictions"] == [{"date": "2026-08-05", "value": 2500.0}]
        assert body["metadata"]["symbol"] == "GC=F"
        assert body["performance_metrics"] == {"mape": 1.2}

    def test_results_missing_job_is_404(self):
        with patch(f"{NS}.get_forecast_job", new=AsyncMock(return_value=None)):
            response = client.get("/api/v1/forecast/results/nope")
        assert response.status_code == 404

    def test_results_not_completed_is_400(self):
        job = make_job(status="running", result_json=None)
        with patch(f"{NS}.get_forecast_job", new=AsyncMock(return_value=job)):
            response = client.get("/api/v1/forecast/results/job-1")
        assert response.status_code == 400

    def test_results_completed_without_stored_result_is_410(self):
        job = make_job(result_json=None)
        with patch(f"{NS}.get_forecast_job", new=AsyncMock(return_value=job)):
            response = client.get("/api/v1/forecast/results/job-1")
        assert response.status_code == 410


# ---------------------------------------------------------------------------
# /recent endpoint (dashboard feed)
# ---------------------------------------------------------------------------

class TestRecentEndpoint:
    def test_recent_lists_jobs_with_prediction_summary(self):
        jobs = [
            make_job(job_id="job-2", symbol="AAPL", result_json={
                "metadata": {"symbol": "AAPL"},
                "predictions": [
                    {"date": "2026-08-05", "predicted_price": 210.0},
                    {"date": "2026-08-06", "predicted_price": 215.0},
                ],
                "performance_metrics": {"mape": 2.0},
            }),
            make_job(job_id="job-3", status="failed", error_message="No historical data",
                     result_json=None),
        ]
        with patch(f"{NS}.get_recent_forecast_jobs", new=AsyncMock(return_value=jobs)):
            response = client.get("/api/v1/forecast/recent")
        assert response.status_code == 200
        body = response.json()
        assert len(body["jobs"]) == 2
        first = body["jobs"][0]
        assert first["job_id"] == "job-2"
        assert first["symbol"] == "AAPL"
        assert first["last_prediction"] == 215.0
        assert first["status"] == "completed"
        failed = body["jobs"][1]
        assert failed["status"] == "failed"
        assert failed["error_message"] == "No historical data"
        assert failed["last_prediction"] is None
        assert failed["confidence"] is None

    def test_recent_respects_limit_param(self):
        capture = AsyncMock(return_value=[])
        with patch(f"{NS}.get_recent_forecast_jobs", new=capture):
            response = client.get("/api/v1/forecast/recent?limit=5")
        assert response.status_code == 200
        assert capture.await_args.kwargs.get("limit") == 5 or 5 in capture.await_args.args


# ---------------------------------------------------------------------------
# Forecast evaluation metrics persist to ModelPerformance
# ---------------------------------------------------------------------------

class TestPerformancePersistence:
    @pytest.mark.asyncio
    async def test_completed_forecast_saves_performance_metrics(self):
        forecast_payload = {
            "metadata": {"symbol": "GC=F", "model_used": "ensemble"},
            "predictions": [{"date": "2026-08-05", "predicted_price": 2500.0}],
            "performance_metrics": {
                "mape": 21.5, "mae": 717.8, "rmse": 718.2,
                "directional_accuracy": 83.3,
            },
        }
        frame = pd.DataFrame({"Close": [1.0, 2.0]})
        save_perf = AsyncMock()
        session_factory = MagicMock()
        session_factory.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{NS}.update_forecast_job", new=AsyncMock()), \
             patch(f"{NS}.save_model_performance", new=save_perf), \
             patch("app.core.database.AsyncSessionLocal", session_factory), \
             patch(f"{NS}.DataService") as data_service_cls, \
             patch(f"{NS}.ForecastService") as forecast_service_cls:
            data_service_cls.return_value.get_historical_data = AsyncMock(return_value=frame)
            forecast_service_cls.return_value.forecast = AsyncMock(return_value=forecast_payload)
            await process_single_forecast(
                job_id="perf-job-12345678",
                symbol="XAU",
                forecast_horizon=7,
                model_type="ensemble",
                include_confidence=True,
                include_features=False,
            )

        save_perf.assert_awaited_once()
        kwargs = save_perf.await_args.kwargs
        assert kwargs["model_type"] == "ensemble"
        assert kwargs["symbol"] == "XAU"
        assert kwargs["mape"] == 21.5
        assert kwargs["directional_accuracy"] == 83.3
        assert kwargs["version"].startswith("forecast-")

    @pytest.mark.asyncio
    async def test_forecast_without_metrics_saves_nothing(self):
        forecast_payload = {"metadata": {}, "predictions": []}
        frame = pd.DataFrame({"Close": [1.0, 2.0]})
        save_perf = AsyncMock()
        session_factory = MagicMock()
        session_factory.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{NS}.update_forecast_job", new=AsyncMock()), \
             patch(f"{NS}.save_model_performance", new=save_perf), \
             patch("app.core.database.AsyncSessionLocal", session_factory), \
             patch(f"{NS}.DataService") as data_service_cls, \
             patch(f"{NS}.ForecastService") as forecast_service_cls:
            data_service_cls.return_value.get_historical_data = AsyncMock(return_value=frame)
            forecast_service_cls.return_value.forecast = AsyncMock(return_value=forecast_payload)
            await process_single_forecast(
                job_id="perf-job-empty",
                symbol="XAU",
                forecast_horizon=7,
                model_type="ensemble",
                include_confidence=True,
                include_features=False,
            )

        save_perf.assert_not_awaited()
