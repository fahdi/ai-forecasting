"""Coverage tests for app.services.forecast_service and
app.api.v1.endpoints.forecast (100% line coverage when run standalone).

All ML model classes and the yfinance-backed DataService are mocked at the
module boundary; endpoint background tasks run synchronously under TestClient
against the sqlite database configured in tests/conftest.py.
"""

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app.services.forecast_service as fs_mod
from app.core.config import settings
from app.main import app
from app.services.forecast_service import ForecastService

API = "/api/v1/forecast"
EP = "app.api.v1.endpoints.forecast"

client = TestClient(app)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_data(n):
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    rng = np.random.RandomState(0)
    close = 100.0 + np.cumsum(rng.randn(n))
    return pd.DataFrame(
        {
            "open": close + 0.5,
            "close": close,
            "volume": rng.randint(100, 1000, n).astype(float),
            "symbol": "AAPL",
        },
        index=idx,
    )


def preds(n, base=100.0):
    return [
        {
            "date": f"2024-01-{i + 1:02d}",
            "predicted_price": base + ((-1) ** i) * i,
            "probability_up": 0.5,
        }
        for i in range(n)
    ]


class FakeModel:
    """Sync model with feature importances for the single-model path."""

    def __init__(self, importances=True):
        if importances:
            self.feature_importances_ = np.array([0.5, 0.3, 0.2])

    def predict(self, X):
        return np.linspace(100.0, 110.0, len(X))


@pytest.fixture
def svc(tmp_path):
    with patch("app.services.forecast_service.ModelManager"), patch(
        "app.services.forecast_service.FeatureEngineer"
    ), patch("app.services.forecast_service.EnsembleModel"):
        service = ForecastService()
    service.results_path = str(tmp_path / "results")
    os.makedirs(service.results_path, exist_ok=True)
    return service


def enough():
    return make_data(settings.MIN_HISTORICAL_DATA_DAYS + 60)


# ---------------------------------------------------------------------------
# ForecastService.forecast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forecast_empty_data_raises(svc):
    with pytest.raises(ValueError, match="Empty dataset"):
        await svc.forecast(pd.DataFrame(), "AAPL", horizon=5)


@pytest.mark.asyncio
async def test_forecast_insufficient_data_raises(svc):
    with pytest.raises(ValueError, match="Insufficient historical data"):
        await svc.forecast(make_data(3), "AAPL", horizon=5)


@pytest.mark.asyncio
async def test_forecast_ensemble_success_with_features(svc):
    data = enough()
    svc.feature_engineer.engineer_features = AsyncMock(return_value=data.copy())
    svc.ensemble_model.train_and_predict = AsyncMock(
        return_value={
            "predictions": preds(3),
            "confidence": 0.9,
            "feature_importance": {"close": 1.0},
        }
    )
    result = await svc.forecast(
        data, "AAPL", horizon=5, include_features=True
    )
    assert result["metadata"]["symbol"] == "AAPL"
    assert result["metadata"]["model_used"] == "ensemble"
    assert result["metadata"]["confidence"] == 0.9
    assert len(result["predictions"]) == 3
    assert result["feature_importance"] == {"close": 1.0}
    assert set(result["performance_metrics"]) == {
        "mae",
        "mape",
        "rmse",
        "directional_accuracy",
    }


@pytest.mark.asyncio
async def test_forecast_single_model_success(svc):
    data = enough()
    svc.feature_engineer.engineer_features = AsyncMock(return_value=data.copy())
    svc.model_manager.get_or_train_model = AsyncMock(return_value=FakeModel())
    result = await svc.forecast(
        data,
        "AAPL",
        horizon=5,
        model_type="xgboost",
        include_confidence=True,
        include_features=True,
    )
    assert result["metadata"]["model_used"] == "xgboost"
    assert len(result["predictions"]) == 5
    first = result["predictions"][0]
    assert {"date", "predicted_price", "probability_up"} <= set(first)
    assert "confidence_lower" in first and "confidence_upper" in first
    assert result["feature_importance"]


@pytest.mark.asyncio
async def test_forecast_single_model_no_confidence_no_features(svc):
    data = enough()
    svc.feature_engineer.engineer_features = AsyncMock(return_value=data.copy())
    svc.model_manager.get_or_train_model = AsyncMock(
        return_value=FakeModel(importances=False)
    )
    result = await svc.forecast(
        data,
        "AAPL",
        horizon=4,
        model_type="lightgbm",
        include_confidence=False,
        include_features=False,
    )
    assert "confidence_lower" not in result["predictions"][0]
    assert "feature_importance" not in result


@pytest.mark.asyncio
async def test_forecast_ensemble_error_propagates(svc):
    data = enough()
    svc.feature_engineer.engineer_features = AsyncMock(return_value=data.copy())
    svc.ensemble_model.train_and_predict = AsyncMock(
        side_effect=RuntimeError("ensemble boom")
    )
    with pytest.raises(RuntimeError, match="ensemble boom"):
        await svc.forecast(data, "AAPL", horizon=5)


@pytest.mark.asyncio
async def test_forecast_single_model_error_propagates(svc):
    data = enough()
    svc.feature_engineer.engineer_features = AsyncMock(return_value=data.copy())
    svc.model_manager.get_or_train_model = AsyncMock(
        side_effect=RuntimeError("train boom")
    )
    with pytest.raises(RuntimeError, match="train boom"):
        await svc.forecast(data, "AAPL", horizon=5, model_type="xgboost")


# ---------------------------------------------------------------------------
# _prepare_forecast_data
# ---------------------------------------------------------------------------

def test_prepare_forecast_data_success(svc):
    X, y = svc._prepare_forecast_data(make_data(30), horizon=5)
    assert len(X) == len(y) == 25
    assert "target" not in X.columns
    assert "symbol" not in X.columns


def test_prepare_forecast_data_error(svc):
    bad = pd.DataFrame({"open": [1.0, 2.0, 3.0]})  # no 'close' column
    with pytest.raises(KeyError):
        svc._prepare_forecast_data(bad, horizon=1)


# ---------------------------------------------------------------------------
# _calculate_confidence_intervals
# ---------------------------------------------------------------------------

def test_confidence_intervals_success(svc):
    intervals = svc._calculate_confidence_intervals(
        np.array([100.0, 102.0, 104.0]), "xgboost"
    )
    assert len(intervals) == 3
    for (lower, upper), pred in zip(intervals, [100.0, 102.0, 104.0]):
        assert lower <= pred <= upper


def test_confidence_intervals_fallback(svc, monkeypatch):
    monkeypatch.setattr(
        fs_mod.np, "std", MagicMock(side_effect=RuntimeError("std boom"))
    )
    intervals = svc._calculate_confidence_intervals(np.array([100.0, 200.0]), "x")
    assert intervals == [(90.0, 110.00000000000001), (180.0, 220.00000000000003)]


# ---------------------------------------------------------------------------
# _calculate_performance_metrics
# ---------------------------------------------------------------------------

def test_performance_metrics_actual_longer(svc):
    actual = pd.Series([100.0, 101.0, 99.0, 102.0, 103.0])
    metrics = svc._calculate_performance_metrics(actual, preds(3))
    assert metrics["mae"] >= 0.0
    assert metrics["rmse"] >= 0.0


def test_performance_metrics_actual_shorter_hits_fallback(svc):
    # actual shorter than predictions: tail() cannot equalize the lengths,
    # numpy broadcasting fails, and the zeroed fallback is returned.
    actual = pd.Series([100.0, 101.0])
    metrics = svc._calculate_performance_metrics(actual, preds(4))
    assert metrics == {
        "mae": 0.0,
        "mape": 0.0,
        "rmse": 0.0,
        "directional_accuracy": 0.0,
    }


# ---------------------------------------------------------------------------
# save / load forecast results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_load_forecast_result(svc):
    job_id = str(uuid.uuid4())
    path = await svc.save_forecast_result({"hello": "world"}, job_id)
    assert os.path.exists(path)
    with open(path) as f:
        assert json.load(f) == {"hello": "world"}
    loaded = await svc.load_forecast_result(job_id)
    assert loaded == {"hello": "world"}


@pytest.mark.asyncio
async def test_save_forecast_result_error(svc, tmp_path):
    svc.results_path = str(tmp_path / "does" / "not" / "exist")
    with pytest.raises(FileNotFoundError):
        await svc.save_forecast_result({"a": 1}, "job-x")


@pytest.mark.asyncio
async def test_load_forecast_result_missing(svc):
    with pytest.raises(FileNotFoundError, match="Forecast result not found"):
        await svc.load_forecast_result("no-such-job")


# ---------------------------------------------------------------------------
# batch_forecast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_forecast_mixed_outcomes(svc):
    async def fake_forecast(data, symbol, horizon, model_type,
                            include_confidence, include_features):
        if symbol == "BAD":
            raise RuntimeError("per-symbol boom")
        return {"metadata": {"symbol": symbol}, "predictions": []}

    svc.forecast = AsyncMock(side_effect=fake_forecast)
    data_dict = {
        "GOOD": make_data(10),
        "BAD": make_data(10),
        "EMPTY": pd.DataFrame(),
        # "MISSING" intentionally absent -> data_dict.get returns None
    }
    result = await svc.batch_forecast(
        ["GOOD", "BAD", "EMPTY", "MISSING"], data_dict, horizon=5
    )
    assert result["total_symbols"] == 4
    assert result["successful_forecasts"] == 1
    assert result["results"]["GOOD"]["metadata"]["symbol"] == "GOOD"
    assert result["results"]["BAD"] == {"error": "per-symbol boom"}
    assert result["results"]["EMPTY"] == {"error": "No data available"}
    assert result["results"]["MISSING"] == {"error": "No data available"}


@pytest.mark.asyncio
async def test_batch_forecast_outer_error(svc):
    with pytest.raises(TypeError):
        await svc.batch_forecast(None, {}, horizon=5)


# ===========================================================================
# Endpoint tests: app/api/v1/endpoints/forecast.py
# ===========================================================================

def _mock_services(historical=None, forecast_side_effect=None):
    """Patch DataService/ForecastService inside the endpoint module."""
    ds_cls = patch(f"{EP}.DataService")
    fs_cls = patch(f"{EP}.ForecastService")
    return ds_cls, fs_cls, historical, forecast_side_effect


def test_single_forecast_success_and_status():
    with patch(f"{EP}.DataService") as ds_cls, patch(f"{EP}.ForecastService") as fs_cls:
        ds_cls.return_value.get_historical_data = AsyncMock(
            return_value=pd.DataFrame({"close": [1.0, 2.0]})
        )
        fs_cls.return_value.forecast = AsyncMock(
            return_value={"metadata": {}, "predictions": []}
        )
        resp = client.post(f"{API}/single", json={"symbol": "aapl"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    job_id = body["job_id"]

    # Background task ran synchronously and completed the job.
    status = client.get(f"{API}/status/{job_id}")
    assert status.status_code == 200
    data = status.json()
    assert data["status"] == "completed"
    assert data["symbol"] == "AAPL"
    assert data["error_message"] is None


def test_single_forecast_create_job_error():
    with patch(
        f"{EP}.create_forecast_job", AsyncMock(side_effect=RuntimeError("db down"))
    ):
        resp = client.post(f"{API}/single", json={"symbol": "AAPL"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "db down"


def test_single_forecast_background_failure_empty_data():
    with patch(f"{EP}.DataService") as ds_cls, patch(f"{EP}.ForecastService"):
        ds_cls.return_value.get_historical_data = AsyncMock(
            return_value=pd.DataFrame()
        )
        resp = client.post(f"{API}/single", json={"symbol": "NODATA"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    status = client.get(f"{API}/status/{job_id}").json()
    assert status["status"] == "failed"
    assert "No historical data available" in status["error_message"]


def test_batch_forecast_success_mixed_symbols():
    async def fake_history(symbol):
        if symbol == "EMPTY":
            return pd.DataFrame()
        return pd.DataFrame({"close": [1.0, 2.0]})

    async def fake_forecast(data, symbol, horizon, model_type,
                            include_confidence, include_features):
        if symbol == "BAD":
            raise RuntimeError("symbol boom")
        return {"metadata": {"symbol": symbol}, "predictions": []}

    with patch(f"{EP}.DataService") as ds_cls, patch(f"{EP}.ForecastService") as fs_cls:
        ds_cls.return_value.get_historical_data = AsyncMock(side_effect=fake_history)
        fs_cls.return_value.forecast = AsyncMock(side_effect=fake_forecast)
        resp = client.post(
            f"{API}/batch", json={"symbols": ["GOOD", "EMPTY", "BAD"]}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "3 symbols" in body["message"]
    job_id = body["job_id"]

    status = client.get(f"{API}/status/{job_id}").json()
    assert status["status"] == "completed"


def test_batch_forecast_too_many_symbols():
    resp = client.post(
        f"{API}/batch", json={"symbols": [f"S{i}" for i in range(101)]}
    )
    assert resp.status_code == 400
    assert "Maximum 100 symbols" in resp.json()["detail"]


def test_batch_forecast_background_outer_failure():
    with patch(f"{EP}.DataService", side_effect=RuntimeError("init boom")):
        resp = client.post(f"{API}/batch", json={"symbols": ["AAA", "BBB"]})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    status = client.get(f"{API}/status/{job_id}").json()
    assert status["status"] == "failed"
    assert status["error_message"] == "init boom"


def test_get_status_not_found():
    resp = client.get(f"{API}/status/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Job not found"


def test_get_status_db_error():
    with patch(
        f"{EP}.get_forecast_job", AsyncMock(side_effect=RuntimeError("db err"))
    ):
        resp = client.get(f"{API}/status/whatever")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "db err"


def test_get_results_not_found_is_404():
    resp = client.get(f"{API}/results/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Job not found"


def test_get_results_not_completed():
    # Create a job whose background task is a no-op so it stays "pending".
    with patch(f"{EP}.process_single_forecast", AsyncMock()):
        resp = client.post(f"{API}/single", json={"symbol": "PEND"})
    job_id = resp.json()["job_id"]

    results = client.get(f"{API}/results/{job_id}")
    assert results.status_code == 400
    assert "not completed" in results.json()["detail"]


def test_get_results_completed():
    with patch(f"{EP}.DataService") as ds_cls, patch(f"{EP}.ForecastService") as fs_cls:
        ds_cls.return_value.get_historical_data = AsyncMock(
            return_value=pd.DataFrame({"close": [1.0, 2.0]})
        )
        fs_cls.return_value.forecast = AsyncMock(
            return_value={"metadata": {}, "predictions": []}
        )
        resp = client.post(f"{API}/single", json={"symbol": "DONE"})
    job_id = resp.json()["job_id"]
    assert client.get(f"{API}/status/{job_id}").json()["status"] == "completed"

    results = client.get(f"{API}/results/{job_id}")
    assert results.status_code == 200
    body = results.json()
    assert body["predictions"] == []
    assert body["metadata"] == {}
