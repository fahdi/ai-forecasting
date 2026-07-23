"""
Boosted-tree ensemble training with walk-forward validation (issue #5, R1/R5).

Direction-over-next-bar classification on crypto features. Chronological
folds only — no shuffling of time series; the label at bar t is derived
exclusively from bar t+1.
"""

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from app.models.crypto_features import FEATURE_COLUMNS, compute_features

# Fast params for tests; production training overrides these.
TINY_PARAMS = {
    "xgboost": {"n_estimators": 20, "max_depth": 3},
    "lightgbm": {"n_estimators": 20, "max_depth": 3, "verbose": -1},
    "catboost": {"iterations": 20, "depth": 3, "verbose": 0},
}

DEFAULT_PARAMS = {
    "xgboost": {"n_estimators": 300, "max_depth": 4, "learning_rate": 0.05,
                "subsample": 0.8, "colsample_bytree": 0.8},
    "lightgbm": {"n_estimators": 300, "max_depth": 4, "learning_rate": 0.05,
                 "subsample": 0.8, "colsample_bytree": 0.8, "verbose": -1},
    "catboost": {"iterations": 300, "depth": 4, "learning_rate": 0.05,
                 "verbose": 0},
}

CALIBRATION_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.001)]


def walk_forward_splits(n: int, n_folds: int, min_train: int) -> List[Tuple[int, int, int]]:
    """Chronological folds as (train_end, test_start, test_end) index bounds.

    Fold k trains on [0, train_end) and tests on [test_start, test_end);
    test windows tile the data after min_train through the final row.
    """
    if n <= min_train + n_folds:
        raise ValueError(f"not enough rows ({n}) for min_train={min_train} "
                         f"and {n_folds} folds")
    test_span = n - min_train
    fold_size = test_span // n_folds
    splits = []
    for k in range(n_folds):
        test_start = min_train + k * fold_size
        test_end = n if k == n_folds - 1 else test_start + fold_size
        splits.append((test_start, test_start, test_end))
    return splits


def build_dataset(
    ohlcv: pd.DataFrame, label_threshold: float = 0.0
) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Features X, next-bar direction label y, and row timestamps.

    Label at bar t: 1 iff close[t+1]/close[t] - 1 > label_threshold. The final
    bar (no next close) and feature warm-up rows are dropped.
    """
    ordered = ohlcv.sort_values("open_time").reset_index(drop=True)
    features = compute_features(ordered)
    next_return = ordered["close"].shift(-1) / ordered["close"] - 1.0
    label = (next_return > label_threshold).astype(int)

    keep = features["complete"] & next_return.notna()
    X = features.loc[keep, FEATURE_COLUMNS].reset_index(drop=True)
    y = label[keep].reset_index(drop=True)
    times = features.loc[keep, "open_time"].reset_index(drop=True)
    return X, y, times


def _make_models(params: Dict[str, dict], seed: int) -> Dict[str, object]:
    from catboost import CatBoostClassifier
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier

    return {
        "xgboost": XGBClassifier(random_state=seed, eval_metric="logloss",
                                 **params["xgboost"]),
        "lightgbm": LGBMClassifier(random_state=seed, **params["lightgbm"]),
        "catboost": CatBoostClassifier(random_seed=seed, **params["catboost"]),
    }


def fit_ensemble(X: pd.DataFrame, y: pd.Series, params: Dict[str, dict],
                 seed: int) -> Dict[str, object]:
    models = _make_models(params, seed)
    for model in models.values():
        model.fit(X, y)
    return models


def predict_prob_long(models: Dict[str, object], X: pd.DataFrame) -> np.ndarray:
    """Ensemble probability of 'long': mean of member probabilities."""
    probs = [model.predict_proba(X)[:, 1] for model in models.values()]
    return np.mean(probs, axis=0)


def evaluate_predictions(y_true: pd.Series, prob_long: np.ndarray) -> Dict:
    predicted = (prob_long >= 0.5).astype(int)
    actual = y_true.to_numpy()
    true_positive = int(((predicted == 1) & (actual == 1)).sum())
    predicted_long = int((predicted == 1).sum())
    actual_long = int((actual == 1).sum())

    calibration = []
    for low, high in CALIBRATION_BUCKETS:
        mask = (prob_long >= low) & (prob_long < high)
        if not mask.any():
            continue
        calibration.append(
            {
                "bucket_low": low,
                "bucket_high": min(high, 1.0),
                "predicted_mean": float(prob_long[mask].mean()),
                "realized_hit_rate": float(actual[mask].mean()),
                "count": int(mask.sum()),
            }
        )

    return {
        "directional_accuracy": float((predicted == actual).mean()),
        "precision_long": true_positive / predicted_long if predicted_long else 0.0,
        "recall_long": true_positive / actual_long if actual_long else 0.0,
        "n_test": int(len(actual)),
        "calibration": calibration,
    }


def train_walk_forward(
    X: pd.DataFrame,
    y: pd.Series,
    n_folds: int,
    min_train: int,
    params: Dict[str, dict] = None,
    seed: int = 42,
) -> Dict:
    params = params or DEFAULT_PARAMS
    folds = []
    for train_end, test_start, test_end in walk_forward_splits(len(X), n_folds, min_train):
        models = fit_ensemble(X.iloc[:train_end], y.iloc[:train_end], params, seed)
        prob = predict_prob_long(models, X.iloc[test_start:test_end])
        folds.append(evaluate_predictions(y.iloc[test_start:test_end], prob))

    total = sum(fold["n_test"] for fold in folds)
    aggregate = {
        "directional_accuracy": sum(
            fold["directional_accuracy"] * fold["n_test"] for fold in folds
        ) / total,
        "n_test": total,
    }
    return {
        "folds": folds,
        "aggregate": aggregate,
        "model_names": list(params),
        "seed": seed,
    }
