"""
Tests for ensemble training with walk-forward validation (issue #5, R1/R5).

Time-series discipline is the point: chronological folds, labels strictly
from the next bar, reproducible seeds. Training runs use tiny model params
on synthetic data to stay fast.
"""

import numpy as np
import pandas as pd
import pytest

from app.models.crypto_features import FEATURE_COLUMNS
from app.models.ensemble_trainer import (
    TINY_PARAMS,
    build_dataset,
    evaluate_predictions,
    train_walk_forward,
    walk_forward_splits,
)


def make_ohlcv(n: int = 400, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, n)))
    return pd.DataFrame(
        {
            "open_time": pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC"),
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": rng.uniform(100, 1000, n),
        }
    )


class TestWalkForwardSplits:
    def test_chronological_and_leak_free(self):
        splits = walk_forward_splits(n=1000, n_folds=5, min_train=200)
        assert len(splits) == 5
        previous_test_end = 200
        for train_end, test_start, test_end in splits:
            assert train_end == test_start, "test must start where training ends"
            assert test_start >= previous_test_end
            assert test_end > test_start
            previous_test_end = test_end
        assert splits[-1][2] == 1000, "folds must cover through the last row"

    def test_min_train_respected(self):
        splits = walk_forward_splits(n=1000, n_folds=4, min_train=300)
        assert splits[0][0] >= 300

    def test_too_little_data_raises(self):
        with pytest.raises(ValueError, match="min_train"):
            walk_forward_splits(n=100, n_folds=5, min_train=200)


class TestDataset:
    def test_label_is_next_bar_direction_only(self):
        ohlcv = make_ohlcv(80)
        X, y, times = build_dataset(ohlcv, label_threshold=0.0)
        # Recompute the expected label for a specific complete row.
        row_time = times.iloc[5]
        position = ohlcv.index[ohlcv["open_time"] == row_time][0]
        expected = int(ohlcv["close"].iloc[position + 1] > ohlcv["close"].iloc[position])
        assert y.iloc[5] == expected

    def test_only_complete_feature_rows_and_no_last_row(self):
        ohlcv = make_ohlcv(80)
        X, y, times = build_dataset(ohlcv)
        # 80 bars - 50 warmup - 1 final row without a next bar = 29
        assert len(X) == len(y) == len(times) == 29
        assert list(X.columns) == FEATURE_COLUMNS
        assert not X.isna().any().any()

    def test_no_feature_lookahead_in_dataset(self):
        ohlcv = make_ohlcv(120)
        X_full, _, times_full = build_dataset(ohlcv)
        X_cut, _, _ = build_dataset(ohlcv.iloc[:100].copy())
        overlap = len(X_cut)
        pd.testing.assert_frame_equal(
            X_full.iloc[:overlap].reset_index(drop=True),
            X_cut.reset_index(drop=True),
            rtol=1e-12,
        )


class TestEvaluation:
    def test_metrics_computed(self):
        y = pd.Series([1, 0, 1, 1, 0, 0, 1, 0])
        prob = np.array([0.9, 0.2, 0.8, 0.4, 0.1, 0.6, 0.7, 0.3])
        metrics = evaluate_predictions(y, prob)
        assert metrics["directional_accuracy"] == pytest.approx(6 / 8)
        assert 0 <= metrics["precision_long"] <= 1
        assert 0 <= metrics["recall_long"] <= 1
        assert metrics["n_test"] == 8
        assert len(metrics["calibration"]) > 0
        for bucket in metrics["calibration"]:
            assert set(bucket) == {"bucket_low", "bucket_high", "predicted_mean",
                                   "realized_hit_rate", "count"}


class TestTraining:
    def test_walk_forward_training_produces_fold_metrics(self):
        X, y, times = build_dataset(make_ohlcv(400))
        result = train_walk_forward(X, y, n_folds=3, min_train=150,
                                    params=TINY_PARAMS, seed=42)
        assert len(result["folds"]) == 3
        for fold in result["folds"]:
            assert 0 <= fold["directional_accuracy"] <= 1
            assert fold["n_test"] > 0
        assert "directional_accuracy" in result["aggregate"]
        assert set(result["model_names"]) == {"xgboost", "lightgbm", "catboost"}

    def test_training_reproducible_with_seed(self):
        X, y, times = build_dataset(make_ohlcv(400))
        a = train_walk_forward(X, y, n_folds=2, min_train=150,
                               params=TINY_PARAMS, seed=42)
        b = train_walk_forward(X, y, n_folds=2, min_train=150,
                               params=TINY_PARAMS, seed=42)
        assert a["aggregate"] == b["aggregate"]
