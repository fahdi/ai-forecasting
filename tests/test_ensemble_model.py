"""
Tests for app.models.ensemble_model.

One end-to-end test trains real (tiny) xgboost/lightgbm/catboost models via
the patched MODEL_CONFIG; the rest exercise the ensemble logic directly with
small fake models so weighting, confidence, and failure paths are all hit
without heavy training.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import app.models.model_manager as mm_module
from app.models.ensemble_model import EnsembleModel

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


class FakeModel:
    """Deterministic stand-in with the interface ModelManager relies on."""

    def __init__(self, value, importances=None):
        self.value = value
        if importances is not None:
            self.feature_importances_ = np.asarray(importances)

    def predict(self, X):
        return np.full(len(X), float(self.value))


class ShortModel:
    """Returns fewer predictions than the requested horizon."""

    def __init__(self, preds):
        self.preds = np.asarray(preds, dtype=float)

    def predict(self, X):
        return self.preds


class BrokenModel:
    def predict(self, X):
        raise RuntimeError("predict exploded")


def make_data(n=60, seed=1):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(
        {"a": rng.normal(size=n), "b": rng.normal(size=n), "c": rng.normal(size=n)}
    )
    y = pd.Series(100.0 + 3.0 * X["a"] - X["b"] + rng.normal(scale=0.2, size=n))
    return X, y


@pytest.fixture
def ensemble(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return EnsembleModel()


class TestTrainAndPredict:
    @pytest.mark.asyncio
    async def test_full_run_with_real_models(self, ensemble):
        X, y = make_data()
        with patch.dict(mm_module.MODEL_CONFIG, TINY_PARAMS):
            result = await ensemble.train_and_predict(
                X, y, horizon=3, include_confidence=True, include_features=True
            )

        assert sorted(result["models_used"]) == ["catboost", "lightgbm", "xgboost"]
        assert pytest.approx(sum(result["weights"].values())) == 1.0
        assert 0.0 <= result["confidence"] <= 1.0

        preds = result["predictions"]
        assert len(preds) == 3
        for p in preds:
            assert set(p) >= {"date", "predicted_price", "probability_up"}
            assert p["probability_up"] == 0.5
            # three models -> confidence interval attached
            assert p["confidence_lower"] <= p["confidence_upper"]

        importance = result["feature_importance"]
        assert set(importance.keys()) == set(X.columns)
        assert list(importance.values()) == sorted(importance.values(), reverse=True)

    @pytest.mark.asyncio
    async def test_one_model_failing_is_skipped(self, ensemble, monkeypatch):
        X, y = make_data()

        async def fake_train(model_type, X_train, y_train, symbol="generic"):
            if model_type == "lightgbm":
                raise RuntimeError("lightgbm broke")
            return FakeModel(100.0 if model_type == "xgboost" else 102.0)

        monkeypatch.setattr(ensemble.model_manager, "train_model", fake_train)
        result = await ensemble.train_and_predict(X, y, horizon=2)

        assert sorted(result["models_used"]) == ["catboost", "xgboost"]
        assert "lightgbm" not in result["weights"]
        assert pytest.approx(sum(result["weights"].values())) == 1.0
        assert len(result["predictions"]) == 2
        # two surviving models -> confidence interval still computed
        assert "confidence_lower" in result["predictions"][0]
        assert result["feature_importance"] is None

    @pytest.mark.asyncio
    async def test_all_models_failing_raises(self, ensemble, monkeypatch):
        X, y = make_data()

        async def fake_train(model_type, X_train, y_train, symbol="generic"):
            raise RuntimeError("nothing trains")

        monkeypatch.setattr(ensemble.model_manager, "train_model", fake_train)
        with pytest.raises(ValueError, match="No models available"):
            await ensemble.train_and_predict(X, y, horizon=2)


class TestMakeEnsemblePredictions:
    @pytest.mark.asyncio
    async def test_broken_model_skipped(self, ensemble):
        X, _ = make_data(n=5)
        ensemble.models = {"good": FakeModel(50.0), "bad": BrokenModel()}
        ensemble.weights = {"good": 0.5, "bad": 0.5}

        preds = await ensemble._make_ensemble_predictions(X.tail(2), 2, True)
        assert len(preds) == 2
        # only the good model contributes; single source -> no interval
        assert preds[0]["predicted_price"] == 50.0
        assert "confidence_lower" not in preds[0]

    @pytest.mark.asyncio
    async def test_short_predictions_truncate_horizon(self, ensemble):
        X, _ = make_data(n=5)
        ensemble.models = {"short": ShortModel([10.0, 11.0])}
        ensemble.weights = {"short": 1.0}

        preds = await ensemble._make_ensemble_predictions(X.tail(4), 4, False)
        assert [p["predicted_price"] for p in preds] == [10.0, 11.0]

    @pytest.mark.asyncio
    async def test_no_confidence_when_disabled(self, ensemble):
        X, _ = make_data(n=4)
        ensemble.models = {"a": FakeModel(10.0), "b": FakeModel(12.0)}
        ensemble.weights = {"a": 0.5, "b": 0.5}

        preds = await ensemble._make_ensemble_predictions(X.tail(2), 2, False)
        assert preds[0]["predicted_price"] == pytest.approx(11.0)
        assert "confidence_lower" not in preds[0]

    @pytest.mark.asyncio
    async def test_no_models_raises(self, ensemble):
        X, _ = make_data(n=3)
        with pytest.raises(ValueError, match="No models available"):
            await ensemble._make_ensemble_predictions(X, 2, True)


class TestPredictionConfidence:
    def test_symmetric_interval(self, ensemble):
        lower, upper = ensemble._calculate_prediction_confidence(
            [100.0, 110.0], [0.5, 0.5]
        )
        assert lower < 105.0 < upper
        assert upper - 105.0 == pytest.approx(105.0 - lower)

    def test_lower_bound_clamped_at_zero(self, ensemble):
        lower, upper = ensemble._calculate_prediction_confidence(
            [1.0, 100.0], [0.5, 0.5]
        )
        assert lower == 0
        assert upper > 100.0

    def test_zero_weights_fall_back_to_range(self, ensemble):
        # np.average raises ZeroDivisionError -> fallback to (min, max)
        assert ensemble._calculate_prediction_confidence(
            [3.0, 7.0], [0.0, 0.0]
        ) == (3.0, 7.0)


class TestEnsembleConfidence:
    def test_uniform_weights_give_low_confidence(self, ensemble):
        ensemble.models = {"a": object(), "b": object()}
        ensemble.weights = {"a": 0.5, "b": 0.5}
        assert ensemble._calculate_ensemble_confidence() == pytest.approx(0.0, abs=1e-6)

    def test_dominant_weight_gives_high_confidence(self, ensemble):
        ensemble.models = {"a": object(), "b": object()}
        ensemble.weights = {"a": 0.99, "b": 0.01}
        assert ensemble._calculate_ensemble_confidence() > 0.8

    def test_no_models_gives_full_confidence(self, ensemble):
        assert ensemble._calculate_ensemble_confidence() == 1.0

    def test_error_returns_default(self, ensemble):
        ensemble.models = {"a": object()}
        ensemble.weights = {"a": "not-a-number"}
        assert ensemble._calculate_ensemble_confidence() == 0.8


class TestFeatureImportanceAggregation:
    def test_weighted_and_sorted(self, ensemble):
        ensemble.models = {
            "m1": FakeModel(1.0, importances=[0.9, 0.1]),
            "m2": FakeModel(2.0, importances=[0.2, 0.8]),
        }
        ensemble.weights = {"m1": 0.75, "m2": 0.25}

        importance = ensemble._get_ensemble_feature_importance(["f1", "f2"])
        assert importance["f1"] == pytest.approx(0.9 * 0.75 + 0.2 * 0.25)
        assert importance["f2"] == pytest.approx(0.1 * 0.75 + 0.8 * 0.25)
        assert list(importance) == ["f1", "f2"]  # sorted descending

    def test_error_returns_empty(self, ensemble):
        ensemble.models = {"m1": FakeModel(1.0, importances=[1.0])}
        ensemble.weights = None  # .get on None -> AttributeError
        assert ensemble._get_ensemble_feature_importance(["f1"]) == {}


class TestModelPerformance:
    def test_metrics_for_good_and_broken_models(self, ensemble):
        X, _ = make_data(n=10)
        y = pd.Series(np.full(10, 100.0))
        ensemble.models = {"good": FakeModel(101.0), "bad": BrokenModel()}
        ensemble.weights = {"good": 1.0}

        perf = ensemble.get_model_performance(X, y)
        assert perf["good"]["mae"] == pytest.approx(1.0)
        assert perf["good"]["rmse"] == pytest.approx(1.0)
        assert perf["good"]["mape"] == pytest.approx(1.0)
        assert perf["good"]["weight"] == 1.0
        assert perf["bad"]["rmse"] == float("inf")
        assert perf["bad"]["weight"] == 0.0

    def test_error_returns_empty(self, ensemble):
        ensemble.models = None
        assert ensemble.get_model_performance(pd.DataFrame(), pd.Series(dtype=float)) == {}


class TestUpdateWeights:
    def test_reweights_by_rmse(self, ensemble):
        X, _ = make_data(n=10)
        y = pd.Series(np.full(10, 100.0))
        ensemble.models = {"close": FakeModel(101.0), "far": FakeModel(110.0)}
        ensemble.weights = {"close": 0.5, "far": 0.5}

        ensemble.update_weights(X, y)
        assert pytest.approx(sum(ensemble.weights.values())) == 1.0
        assert ensemble.weights["close"] > ensemble.weights["far"]

    def test_broken_models_keep_old_weights(self, ensemble):
        X, _ = make_data(n=10)
        y = pd.Series(np.full(10, 100.0))
        ensemble.models = {"bad": BrokenModel()}
        ensemble.weights = {"bad": 0.4}

        ensemble.update_weights(X, y)
        # inf rmse -> skipped, total weight 0 -> no renormalisation
        assert ensemble.weights == {"bad": 0.4}

    def test_error_is_swallowed(self, ensemble, monkeypatch):
        def boom(X, y):
            raise RuntimeError("perf failed")

        monkeypatch.setattr(ensemble, "get_model_performance", boom)
        ensemble.update_weights(pd.DataFrame(), pd.Series(dtype=float))  # no raise


class TestEnsembleInfo:
    def test_info_shape(self, ensemble):
        ensemble.models = {"a": object()}
        ensemble.weights = {"a": 1.0}
        info = ensemble.get_ensemble_info()
        assert info["models"] == ["a"]
        assert info["weights"] == {"a": 1.0}
        assert info["total_models"] == 1
        assert 0.0 <= info["confidence"] <= 1.0
