"""
Tests for app.models.model_manager.

Real (tiny) xgboost/lightgbm/catboost models are trained on small synthetic
data; MODEL_CONFIG is patched to small parameter sets so the suite stays fast.
Disk-facing tests run inside a tmp cwd because ModelManager creates its
"models" directory relative to the working directory.
"""

import os
import pickle
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import app.models.model_manager as mm_module
from app.models.model_manager import ModelManager

TINY_PARAMS = {
    "xgboost": {"n_estimators": 5, "max_depth": 2, "random_state": 42},
    "lightgbm": {
        "n_estimators": 5,
        "max_depth": 2,
        "min_child_samples": 2,
        "random_state": 42,
        "verbose": -1,
    },
    "catboost": {"iterations": 5, "depth": 2, "random_state": 42},
}


@pytest.fixture
def tiny_config():
    with patch.dict(mm_module.MODEL_CONFIG, TINY_PARAMS):
        yield


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return ModelManager()


def make_data(n=40, seed=0):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(
        {"a": rng.normal(size=n), "b": rng.normal(size=n), "c": rng.normal(size=n)}
    )
    y = pd.Series(2.0 * X["a"] - X["b"] + rng.normal(scale=0.1, size=n) + 10.0)
    return X, y


class TestInit:
    def test_creates_models_dir_and_empty_cache(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mgr = ModelManager()
        assert (tmp_path / "models").is_dir()
        assert mgr.model_cache == {}


class TestTrainModel:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_type", ["xgboost", "lightgbm", "catboost"])
    async def test_trains_each_supported_type(self, manager, tiny_config, model_type):
        X, y = make_data()
        model = await manager.train_model(model_type, X, y, symbol="TEST")

        assert hasattr(model, "predict")
        preds = model.predict(X)
        assert len(preds) == len(X)
        # trained model gets cached under symbol_modeltype
        assert manager.model_cache[f"TEST_{model_type}"] is model

    @pytest.mark.asyncio
    async def test_unsupported_type_raises(self, manager, tiny_config):
        X, y = make_data()
        with pytest.raises(ValueError, match="Unsupported model type"):
            await manager.train_model("prophet", X, y)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_type", ["xgboost", "lightgbm", "catboost"])
    async def test_training_failure_propagates(self, manager, tiny_config, model_type):
        # Mismatched X/y lengths make every library's fit() raise, exercising
        # the except path in each _train_* helper and in train_model itself.
        X, y = make_data()
        bad_y = y.iloc[:5]
        with pytest.raises(Exception):
            await manager.train_model(model_type, X, bad_y)


class TestGetOrTrainModel:
    @pytest.mark.asyncio
    async def test_returns_cached_model(self, manager, tiny_config):
        X, y = make_data()
        sentinel = object()
        manager.model_cache["AAPL_xgboost"] = sentinel
        model = await manager.get_or_train_model("xgboost", X, y, symbol="AAPL")
        assert model is sentinel

    @pytest.mark.asyncio
    async def test_loads_model_from_disk(self, manager, tiny_config):
        X, y = make_data()
        trained = await manager.train_model("xgboost", X, y, symbol="AAPL")
        manager.save_model(trained, "AAPL", "xgboost")
        manager.clear_cache()

        loaded = await manager.get_or_train_model("xgboost", X, y, symbol="AAPL")
        np.testing.assert_allclose(loaded.predict(X), trained.predict(X))
        assert "AAPL_xgboost" in manager.model_cache

    @pytest.mark.asyncio
    async def test_trains_new_model_when_absent(self, manager, tiny_config):
        X, y = make_data()
        model = await manager.get_or_train_model("xgboost", X, y, symbol="MSFT")
        assert hasattr(model, "predict")
        assert "MSFT_xgboost" in manager.model_cache

    @pytest.mark.asyncio
    async def test_error_propagates(self, manager, tiny_config):
        X, y = make_data()
        with pytest.raises(ValueError):
            await manager.get_or_train_model("bogus", X, y, symbol="MSFT")


class TestPredict:
    @pytest.mark.asyncio
    async def test_predict_with_trained_model(self, manager, tiny_config):
        X, y = make_data()
        model = await manager.train_model("xgboost", X, y)
        preds = manager.predict(model, X)
        assert isinstance(preds, np.ndarray)
        assert len(preds) == len(X)

    def test_object_without_predict_raises(self, manager):
        with pytest.raises(ValueError, match="does not have predict"):
            manager.predict(object(), pd.DataFrame({"a": [1.0]}))


class ExplodingImportance:
    """feature_importances_ access raises a non-AttributeError, which
    propagates out of hasattr() and into the except branch."""

    @property
    def feature_importances_(self):
        raise RuntimeError("boom")


class TestFeatureImportance:
    @pytest.mark.asyncio
    async def test_importance_sorted_descending(self, manager, tiny_config):
        X, y = make_data(n=60)
        model = await manager.train_model("xgboost", X, y)
        importance = manager.get_feature_importance(model, list(X.columns))
        assert set(importance.keys()) == set(X.columns)
        values = list(importance.values())
        assert values == sorted(values, reverse=True)

    def test_model_without_attribute_returns_empty(self, manager):
        assert manager.get_feature_importance(object(), ["a"]) == {}

    def test_exception_returns_empty(self, manager):
        assert manager.get_feature_importance(ExplodingImportance(), ["a"]) == {}


class TestSaveLoadDelete:
    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, manager, tiny_config):
        X, y = make_data()
        model = await manager.train_model("xgboost", X, y)
        path = manager.save_model(model, "AAPL", "xgboost")
        assert os.path.exists(path)

        loaded = manager.load_model("AAPL", "xgboost")
        np.testing.assert_allclose(loaded.predict(X), model.predict(X))

    def test_save_failure_raises(self, manager):
        manager.models_path = os.path.join("no", "such", "dir")
        with pytest.raises(Exception):
            manager.save_model({"m": 1}, "AAPL", "xgboost")

    def test_load_missing_returns_none(self, manager):
        assert manager.load_model("NOPE", "xgboost") is None

    def test_load_corrupt_file_returns_none(self, manager):
        path = os.path.join(manager.models_path, "BAD_xgboost.pkl")
        with open(path, "wb") as f:
            f.write(b"not a pickle")
        assert manager.load_model("BAD", "xgboost") is None

    def test_delete_existing_model_clears_cache(self, manager):
        path = os.path.join(manager.models_path, "AAPL_xgboost.pkl")
        with open(path, "wb") as f:
            pickle.dump({"m": 1}, f)
        manager.model_cache["AAPL_xgboost"] = {"m": 1}

        assert manager.delete_model("AAPL", "xgboost") is True
        assert not os.path.exists(path)
        assert "AAPL_xgboost" not in manager.model_cache

    def test_delete_missing_returns_false(self, manager):
        assert manager.delete_model("NOPE", "xgboost") is False

    def test_delete_error_returns_false(self, manager):
        path = os.path.join(manager.models_path, "AAPL_xgboost.pkl")
        with open(path, "wb") as f:
            pickle.dump({"m": 1}, f)
        with patch("os.remove", side_effect=OSError("locked")):
            assert manager.delete_model("AAPL", "xgboost") is False


class TestListModels:
    def test_lists_only_parseable_pickles(self, manager):
        for name in ("AAPL_xgboost.pkl", "solo.pkl", "notes.txt"):
            with open(os.path.join(manager.models_path, name), "wb") as f:
                f.write(b"x")

        models = manager.list_models()
        assert models == [
            {"symbol": "AAPL", "model_type": "xgboost", "filename": "AAPL_xgboost.pkl"}
        ]

    def test_error_returns_empty_list(self, manager):
        manager.models_path = os.path.join("no", "such", "dir")
        assert manager.list_models() == []


class TestClearCache:
    def test_clear_cache(self, manager):
        manager.model_cache["k"] = object()
        manager.clear_cache()
        assert manager.model_cache == {}
