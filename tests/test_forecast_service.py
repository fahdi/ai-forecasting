"""Tests for app.services.forecast_service targeting 100% line coverage.

ModelManager / FeatureEngineer / EnsembleModel are mocked at the service
module boundary; file I/O happens inside pytest tmp_path (cwd is switched
because results_path is the relative "results" directory).
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import app.services.forecast_service as fs_mod
from app.core.config import settings
from app.services.forecast_service import ForecastService


def make_data(n=60, start="2024-01-01"):
    idx = pd.date_range(start, periods=n, freq="D")
    rng = np.random.RandomState(42)
    close = 100 + np.cumsum(rng.randn(n))
    return pd.DataFrame(
        {
            "open": close + 0.5,
            "close": close,
            "volume": rng.randint(100, 1000, n).astype(float),
            "symbol": "AAPL",
        },
        index=idx,
    )


def preds_list(n=5, base=100.0):
    return [
        {
            "date": f"2024-03-{i + 1:02d}",
            "predicted_price": base + ((-1) ** i) * i,
            "probability_up": 0.5,
        }
        for i in range(n)
    ]


class NoImportanceModel:
    """Model without feature_importances_ attribute."""

    def __init__(self, values):
        self._values = np.asarray(values, dtype=float)

    def predict(self, X):
        return self._values[: len(X)]


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("app.services.forecast_service.ModelManager"), patch(
        "app.services.forecast_service.FeatureEngineer"
    ), patch("app.services.forecast_service.EnsembleModel"):
        service = ForecastService()
    monkeypatch.setattr(fs_mod, "record_forecast_duration", MagicMock())
    monkeypatch.setattr(settings, "MIN_HISTORICAL_DATA_DAYS", 10)
    return service


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forecast_empty_data_raises(svc):
    with pytest.raises(ValueError, match="Empty dataset"):
        await svc.forecast(pd.DataFrame(), "AAPL", horizon=5)


@pytest.mark.asyncio
async def test_forecast_insufficient_data_raises(svc):
    with pytest.raises(ValueError, match="Insufficient historical data"):
        await svc.forecast(make_data(5), "AAPL", horizon=5)


@pytest.mark.asyncio
async def test_forecast_ensemble_success_with_features(svc):
    data = make_data(60)
    svc.feature_engineer.engineer_features = AsyncMock(return_value=data.copy())
    svc.ensemble_model.train_and_predict = AsyncMock(
        return_value={
            "predictions": preds_list(5),
            "confidence": 0.9,
            "feature_importance": {"close": 0.7, "volume": 0.3},
        }
    )

    result = await svc.forecast(
        data, "AAPL", horizon=5, model_type="ensemble", include_features=True
    )

    meta = result["metadata"]
    assert meta["symbol"] == "AAPL"
    assert meta["model_used"] == "ensemble"
    assert meta["horizon"] == 5
    assert meta["data_points_used"] == 60
    assert meta["confidence"] == 0.9
    assert len(result["predictions"]) == 5
    assert result["feature_importance"] == {"close": 0.7, "volume": 0.3}
    assert set(result["performance_metrics"]) == {
        "mae",
        "mape",
        "rmse",
        "directional_accuracy",
        "evaluation_points",
    }
    fs_mod.record_forecast_duration.assert_called_once()


@pytest.mark.asyncio
async def test_forecast_ensemble_without_features(svc):
    data = make_data(60)
    svc.feature_engineer.engineer_features = AsyncMock(return_value=data.copy())
    svc.ensemble_model.train_and_predict = AsyncMock(
        return_value={"predictions": preds_list(5), "confidence": 0.8}
    )
    result = await svc.forecast(data, "AAPL", horizon=5, include_features=False)
    assert "feature_importance" not in result


@pytest.mark.asyncio
async def test_forecast_single_model_with_confidence_and_features(svc):
    data = make_data(60)
    features = data.copy()
    svc.feature_engineer.engineer_features = AsyncMock(return_value=features)

    n_features = 3  # open, close, volume (symbol excluded)
    model = MagicMock()
    model.predict.return_value = np.array([100.0, 102.0, 99.0, 104.0, 101.0])
    model.feature_importances_ = np.array([0.5, 0.3, 0.2])
    svc.model_manager.get_or_train_model = AsyncMock(return_value=model)

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
    assert first["confidence_lower"] <= first["predicted_price"] <= first["confidence_upper"]
    assert len(result["feature_importance"]) == n_features


@pytest.mark.asyncio
async def test_forecast_single_model_plain(svc):
    data = make_data(60)
    svc.feature_engineer.engineer_features = AsyncMock(return_value=data.copy())
    model = NoImportanceModel([100.0, 101.0, 102.0, 103.0, 104.0])
    svc.model_manager.get_or_train_model = AsyncMock(return_value=model)

    result = await svc.forecast(
        data,
        "AAPL",
        horizon=5,
        model_type="lightgbm",
        include_confidence=False,
        include_features=False,
    )

    assert all("confidence_lower" not in p for p in result["predictions"])
    assert "feature_importance" not in result


@pytest.mark.asyncio
async def test_forecast_error_propagates(svc):
    data = make_data(60)
    svc.feature_engineer.engineer_features = AsyncMock(
        side_effect=RuntimeError("feature failure")
    )
    with pytest.raises(RuntimeError, match="feature failure"):
        await svc.forecast(data, "AAPL", horizon=5)


# ---------------------------------------------------------------------------
# _prepare_forecast_data
# ---------------------------------------------------------------------------

def test_prepare_forecast_data(svc):
    data = make_data(20)
    data.iloc[0, data.columns.get_loc("open")] = np.nan  # dropped up front
    X, y = svc._prepare_forecast_data(data, horizon=5)
    assert "target" not in X.columns
    assert "symbol" not in X.columns
    assert len(X) == len(y) == 14  # 20 - 1 NaN row - 5 shifted rows
    assert list(X.columns) == ["open", "close", "volume"]


def test_prepare_forecast_data_error(svc):
    with pytest.raises(KeyError):
        svc._prepare_forecast_data(pd.DataFrame({"foo": [1, 2, 3]}), horizon=1)


# ---------------------------------------------------------------------------
# _ensemble_forecast / _single_model_forecast error paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensemble_forecast_error_propagates(svc):
    svc.ensemble_model.train_and_predict = AsyncMock(
        side_effect=RuntimeError("ensemble broke")
    )
    with pytest.raises(RuntimeError, match="ensemble broke"):
        await svc._ensemble_forecast(pd.DataFrame(), pd.Series(dtype=float), 5, True, False)


@pytest.mark.asyncio
async def test_single_model_forecast_error_propagates(svc):
    svc.model_manager.get_or_train_model = AsyncMock(
        side_effect=RuntimeError("training broke")
    )
    with pytest.raises(RuntimeError, match="training broke"):
        await svc._single_model_forecast(
            pd.DataFrame(), pd.Series(dtype=float), 5, "xgboost", True, False
        )


# ---------------------------------------------------------------------------
# _calculate_confidence_intervals
# ---------------------------------------------------------------------------

def test_calculate_confidence_intervals(svc):
    preds = np.array([100.0, 110.0, 120.0])
    intervals = svc._calculate_confidence_intervals(preds, "xgboost")
    assert len(intervals) == 3
    for pred, (lower, upper) in zip(preds, intervals):
        assert lower <= pred <= upper
        assert lower >= 0


def test_calculate_confidence_intervals_fallback(svc):
    preds = np.array([100.0, 200.0])
    with patch("app.services.forecast_service.np.std", side_effect=Exception("boom")):
        intervals = svc._calculate_confidence_intervals(preds, "xgboost")
    assert intervals[0] == (pytest.approx(90.0), pytest.approx(110.0))
    assert intervals[1] == (pytest.approx(180.0), pytest.approx(220.0))


# ---------------------------------------------------------------------------
# _calculate_performance_metrics
# ---------------------------------------------------------------------------

def test_calculate_performance_metrics_equal_lengths(svc):
    actual = pd.Series([100.0, 102.0, 101.0, 103.0, 105.0])
    preds = [{"predicted_price": v} for v in [100.0, 102.0, 101.0, 103.0, 105.0]]
    metrics = svc._calculate_performance_metrics(actual, preds)
    assert metrics["mae"] == 0.0
    assert metrics["rmse"] == 0.0
    assert metrics["directional_accuracy"] == 100.0


def test_calculate_performance_metrics_actual_longer(svc):
    actual = pd.Series([90.0, 95.0, 100.0, 102.0, 101.0, 103.0, 105.0])
    preds = [{"predicted_price": v} for v in [100.0, 101.0, 102.0]]
    metrics = svc._calculate_performance_metrics(actual, preds)
    assert metrics["mae"] > 0


def test_calculate_performance_metrics_actual_shorter_returns_zeros(svc):
    # BUG (suspected): actual.tail(len(predictions)) cannot lengthen a short
    # series, so the arrays mismatch and the except path returns zeros.
    actual = pd.Series([100.0, 101.0])
    preds = [{"predicted_price": v} for v in [100.0, 101.0, 102.0, 103.0, 104.0]]
    metrics = svc._calculate_performance_metrics(actual, preds)
    assert metrics == {
        "mae": 0.0,
        "mape": 0.0,
        "rmse": 0.0,
        "directional_accuracy": 0.0,
    }


# ---------------------------------------------------------------------------
# save / load forecast result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_load_forecast_result(svc, tmp_path):
    payload = {"metadata": {"symbol": "AAPL"}, "predictions": preds_list(2)}
    path = await svc.save_forecast_result(payload, "job-123")
    assert os.path.exists(path)
    loaded = await svc.load_forecast_result("job-123")
    assert loaded == json.loads(json.dumps(payload, default=str))


@pytest.mark.asyncio
async def test_save_forecast_result_error(svc, tmp_path):
    svc.results_path = str(tmp_path / "does-not-exist")
    with pytest.raises(FileNotFoundError):
        await svc.save_forecast_result({"a": 1}, "job-err")


@pytest.mark.asyncio
async def test_load_forecast_result_missing(svc):
    with pytest.raises(FileNotFoundError, match="Forecast result not found"):
        await svc.load_forecast_result("no-such-job")


# ---------------------------------------------------------------------------
# batch_forecast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_forecast_mixed_outcomes(svc):
    async def fake_forecast(data, symbol, horizon, model_type, include_confidence, include_features):
        if symbol == "FAIL":
            raise RuntimeError("model exploded")
        return {"metadata": {"symbol": symbol}}

    with patch.object(svc, "forecast", side_effect=fake_forecast):
        result = await svc.batch_forecast(
            symbols=["AAPL", "MISSING", "FAIL"],
            data_dict={"AAPL": make_data(20), "FAIL": make_data(20)},
            horizon=5,
        )

    assert result["total_symbols"] == 3
    assert result["successful_forecasts"] == 1
    assert result["results"]["AAPL"] == {"metadata": {"symbol": "AAPL"}}
    assert result["results"]["MISSING"] == {"error": "No data available"}
    assert result["results"]["FAIL"] == {"error": "model exploded"}


@pytest.mark.asyncio
async def test_batch_forecast_outer_error_propagates(svc):
    with pytest.raises(TypeError):
        await svc.batch_forecast(symbols=None, data_dict={}, horizon=5)


class TestMetricsSampleSize:
    def test_metrics_report_evaluation_points(self):
        """A hit rate without its sample size presents noise as signal; the
        UI shows 'n=' so tiny holdouts read as tentative, not authoritative."""
        import pandas as pd
        from app.services.forecast_service import ForecastService

        service = ForecastService()
        actual = pd.Series([100.0, 101.0, 99.0, 102.0, 103.0, 101.0, 104.0])
        predictions = [{"predicted_price": v} for v in [100.5, 100.0, 99.5, 101.0, 104.0, 102.0, 103.0]]
        metrics = service._calculate_performance_metrics(actual, predictions)
        assert metrics["evaluation_points"] == 6  # diff over 7 aligned points
        assert 0.0 <= metrics["directional_accuracy"] <= 100.0
