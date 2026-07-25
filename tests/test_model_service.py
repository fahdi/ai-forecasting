"""Tests for app.services.model_service targeting 100% line coverage.

ModelManager / FeatureEngineer / DataService are mocked; model files are
real pickles written inside pytest tmp_path.
"""

import json
import pickle
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import app.services.model_service as ms_mod
from app.core.config import settings
from app.services.model_service import ModelService


class FakeModel:
    """Picklable model with a deterministic predict()."""

    def predict(self, X):
        return np.arange(len(X), dtype=float) + 100.0


def make_data(n=50, start="2024-01-01"):
    idx = pd.date_range(start, periods=n, freq="D")
    rng = np.random.RandomState(7)
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


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_STORAGE_PATH", str(tmp_path / "models"))
    with patch("app.services.model_service.ModelManager"), patch(
        "app.services.model_service.FeatureEngineer"
    ):
        service = ModelService()
    return service


def write_model(svc, symbol, model_type, version, with_metrics=False):
    path = f"{svc.models_path}/{symbol}_{model_type}_{version}.pkl"
    with open(path, "wb") as f:
        pickle.dump(FakeModel(), f)
    if with_metrics:
        metrics_path = path.replace(".pkl", "_metrics.json")
        with open(metrics_path, "w") as f:
            json.dump({"mape": 1.5}, f)
    return path


def patched_data_service(df):
    """Patch DataService used inside model_service via local import."""
    instance = MagicMock()
    instance.get_historical_data = AsyncMock(return_value=df)
    return patch("app.services.data_service.DataService", return_value=instance)


# ---------------------------------------------------------------------------
# train_model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_train_model_success(svc, tmp_path):
    data = make_data(50)
    svc.feature_engineer.engineer_features = AsyncMock(return_value=data.copy())
    svc.model_manager.train_model = AsyncMock(return_value=FakeModel())

    with patched_data_service(data):
        result = await svc.train_model("AAPL", "xgboost")

    assert result["symbol"] == "AAPL"
    assert result["model_type"] == "xgboost"
    assert result["data_points"] == 50
    assert result["test_size"] == 0.2
    assert set(result["performance"]) == {"mae", "mape", "rmse", "directional_accuracy"}
    saved = list((tmp_path / "models").glob("AAPL_xgboost_*.pkl"))
    assert len(saved) == 1
    metrics_files = list((tmp_path / "models").glob("AAPL_xgboost_*_metrics.json"))
    assert len(metrics_files) == 1


@pytest.mark.asyncio
async def test_train_model_existing_not_retrained(svc):
    write_model(svc, "AAPL", "rf", "20240101_000000", with_metrics=True)
    svc.model_manager.train_model = AsyncMock()

    result = await svc.train_model("AAPL", "rf", retrain_existing=False)

    assert result["symbol"] == "AAPL"
    assert result["performance"] == {"mape": 1.5}
    svc.model_manager.train_model.assert_not_called()


@pytest.mark.asyncio
async def test_train_model_no_data_raises(svc):
    with patched_data_service(pd.DataFrame()):
        with pytest.raises(ValueError, match="No data available"):
            await svc.train_model("EMPTY", "xgboost")


# ---------------------------------------------------------------------------
# _prepare_training_data
# ---------------------------------------------------------------------------

def test_prepare_training_data(svc):
    data = make_data(20)
    data.iloc[0, data.columns.get_loc("open")] = np.nan  # dropped up front
    X, y = svc._prepare_training_data(data)
    assert "target" not in X.columns
    assert "symbol" not in X.columns
    assert len(X) == len(y) == 18  # 20 - 1 NaN row - 1 shifted row


def test_prepare_training_data_error(svc):
    with pytest.raises(KeyError):
        svc._prepare_training_data(pd.DataFrame({"foo": [1.0, 2.0]}))


# ---------------------------------------------------------------------------
# _calculate_performance_metrics
# ---------------------------------------------------------------------------

def test_calculate_performance_metrics(svc):
    y_true = pd.Series([100.0, 102.0, 101.0, 103.0])
    y_pred = np.array([100.0, 102.0, 101.0, 103.0])
    metrics = svc._calculate_performance_metrics(y_true, y_pred)
    assert metrics["mae"] == 0.0
    assert metrics["mape"] == 0.0
    assert metrics["rmse"] == 0.0
    assert metrics["directional_accuracy"] == 100.0


def test_calculate_performance_metrics_error_returns_zeros(svc):
    y_true = pd.Series([100.0, 101.0])
    y_pred = np.array([100.0, 101.0, 102.0, 103.0])  # length mismatch
    metrics = svc._calculate_performance_metrics(y_true, y_pred)
    assert metrics == {
        "mae": 0.0,
        "mape": 0.0,
        "rmse": 0.0,
        "directional_accuracy": 0.0,
    }


# ---------------------------------------------------------------------------
# _save_model / _save_performance_metrics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_model_error_propagates(svc):
    with patch("app.services.model_service.pickle.dump", side_effect=OSError("disk")):
        with pytest.raises(OSError, match="disk"):
            await svc._save_model(FakeModel(), "AAPL", "rf", "v1")


@pytest.mark.asyncio
async def test_save_performance_metrics_error_propagates(svc, tmp_path):
    svc.models_path = str(tmp_path / "missing-dir")
    with pytest.raises(FileNotFoundError):
        await svc._save_performance_metrics("AAPL", "rf", "v1", {"mape": 1.0})


# ---------------------------------------------------------------------------
# _get_model_path / _get_metrics_path
# ---------------------------------------------------------------------------

def test_get_model_path_with_version(svc):
    path = svc._get_model_path("AAPL", "rf", "v1")
    assert path.endswith("AAPL_rf_v1.pkl")


def test_get_model_path_latest_existing(svc):
    created = write_model(svc, "AAPL", "rf", "20240101_000000")
    assert svc._get_model_path("AAPL", "rf") == created


def test_get_model_path_no_files(svc):
    assert svc._get_model_path("GHOST", "rf").endswith("GHOST_rf_latest.pkl")


def test_get_metrics_path(svc):
    assert svc._get_metrics_path("AAPL", "rf", "v1").endswith("AAPL_rf_v1_metrics.json")


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_models(svc, tmp_path):
    write_model(svc, "AAPL", "rf", "20240101_000000", with_metrics=True)
    write_model(svc, "MSFT", "xgb", "20240102_000000")
    # malformed name (fewer than 3 underscore parts) is skipped
    (tmp_path / "models" / "badname.pkl").write_bytes(b"x")

    models = await svc.list_models()
    assert len(models) == 2
    by_symbol = {m["symbol"]: m for m in models}
    assert by_symbol["AAPL"]["performance"] == {"mape": 1.5}
    assert by_symbol["AAPL"]["version"] == "20240101_000000"
    assert by_symbol["MSFT"]["performance"] is None
    # sorted by last_trained descending
    assert models[0]["last_trained"] >= models[1]["last_trained"]


@pytest.mark.asyncio
async def test_list_models_filters(svc):
    write_model(svc, "AAPL", "rf", "20240101_000000")
    write_model(svc, "MSFT", "xgb", "20240102_000000")

    only_aapl = await svc.list_models(symbol="AAPL")
    assert [m["symbol"] for m in only_aapl] == ["AAPL"]

    only_xgb = await svc.list_models(model_type="xgb")
    assert [m["model_type"] for m in only_xgb] == ["xgb"]


@pytest.mark.asyncio
async def test_list_models_error_returns_empty(svc):
    with patch.object(ms_mod.os, "listdir", side_effect=OSError("io error")):
        assert await svc.list_models() == []


# ---------------------------------------------------------------------------
# get_model_info
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_model_info_with_version_and_metrics(svc):
    write_model(svc, "AAPL", "rf", "v1", with_metrics=True)
    info = await svc.get_model_info("rf", "AAPL", version="v1")
    assert info["version"] == "v1"
    assert info["performance"] == {"mape": 1.5}
    assert info["file_size"] > 0


@pytest.mark.asyncio
async def test_get_model_info_without_metrics(svc):
    write_model(svc, "AAPL", "rf", "v2")
    info = await svc.get_model_info("rf", "AAPL", version="v2")
    assert info["performance"] is None


@pytest.mark.asyncio
async def test_get_model_info_missing_returns_none(svc):
    assert await svc.get_model_info("rf", "GHOST") is None


@pytest.mark.asyncio
async def test_get_model_info_error_returns_none(svc):
    write_model(svc, "AAPL", "rf", "v1")
    with patch.object(ms_mod.os, "stat", side_effect=RuntimeError("stat broke")):
        assert await svc.get_model_info("rf", "AAPL", version="v1") is None


# ---------------------------------------------------------------------------
# delete_model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_model_with_metrics(svc, tmp_path):
    write_model(svc, "AAPL", "rf", "v1", with_metrics=True)
    assert await svc.delete_model("rf", "AAPL", version="v1") is True
    assert list((tmp_path / "models").iterdir()) == []


@pytest.mark.asyncio
async def test_delete_model_missing_returns_false(svc):
    assert await svc.delete_model("rf", "GHOST", version="v1") is False


@pytest.mark.asyncio
async def test_delete_model_error_returns_false(svc):
    write_model(svc, "AAPL", "rf", "v1")
    with patch.object(ms_mod.os, "remove", side_effect=OSError("locked")):
        assert await svc.delete_model("rf", "AAPL", version="v1") is False


# ---------------------------------------------------------------------------
# load_model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_model_success(svc):
    write_model(svc, "AAPL", "rf", "v1")
    model = await svc.load_model("rf", "AAPL", version="v1")
    assert isinstance(model, FakeModel)


@pytest.mark.asyncio
async def test_load_model_missing_returns_none(svc):
    assert await svc.load_model("rf", "GHOST", version="v1") is None


@pytest.mark.asyncio
async def test_load_model_corrupt_returns_none(svc, tmp_path):
    (tmp_path / "models" / "AAPL_rf_v1.pkl").write_bytes(b"not a pickle")
    assert await svc.load_model("rf", "AAPL", version="v1") is None


# ---------------------------------------------------------------------------
# evaluate_model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_model_success(svc):
    write_model(svc, "AAPL", "rf", "v1")
    data = make_data(50)
    svc.feature_engineer.engineer_features = AsyncMock(return_value=data.copy())

    with patched_data_service(data):
        result = await svc.evaluate_model("rf", "AAPL", version="v1")

    assert result["symbol"] == "AAPL"
    assert result["model_type"] == "rf"
    assert result["version"] == "v1"
    assert result["test_size"] == 10  # 20% of the 49 usable rows, rounded up
    assert set(result["performance"]) == {"mae", "mape", "rmse", "directional_accuracy"}


@pytest.mark.asyncio
async def test_evaluate_model_no_model_returns_none(svc):
    assert await svc.evaluate_model("rf", "GHOST", version="v1") is None


@pytest.mark.asyncio
async def test_evaluate_model_no_data_returns_none(svc):
    write_model(svc, "AAPL", "rf", "v1")
    with patched_data_service(pd.DataFrame()):
        assert await svc.evaluate_model("rf", "AAPL", version="v1") is None


@pytest.mark.asyncio
async def test_evaluate_model_error_returns_none(svc):
    write_model(svc, "AAPL", "rf", "v1")
    data = make_data(50)
    svc.feature_engineer.engineer_features = AsyncMock(
        side_effect=RuntimeError("features broke")
    )
    with patched_data_service(data):
        assert await svc.evaluate_model("rf", "AAPL", version="v1") is None
