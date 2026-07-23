"""
Tests for app.models.crypto_features (issue #4).

Contract: pure function `compute_features(ohlcv)` — OHLCV in, features out.
No I/O, deterministic, and provably free of lookahead bias.
"""

import numpy as np
import pandas as pd
import pytest

from app.models.crypto_features import (
    FEATURE_COLUMNS,
    WARMUP_BARS,
    compute_features,
)


def make_ohlcv(n: int = 120, seed: int = 7) -> pd.DataFrame:
    """Synthetic but realistic OHLCV frame with a fixed seed."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    high = close * (1 + rng.uniform(0, 0.005, n))
    low = close * (1 - rng.uniform(0, 0.005, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.uniform(100, 1000, n)
    open_time = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": open_time,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


class TestSchema:
    def test_returns_expected_feature_columns(self):
        features = compute_features(make_ohlcv())
        for col in FEATURE_COLUMNS:
            assert col in features.columns, f"missing feature column: {col}"
        assert "complete" in features.columns

    def test_output_row_count_matches_input(self):
        df = make_ohlcv(80)
        assert len(compute_features(df)) == 80

    def test_missing_required_column_raises(self):
        df = make_ohlcv().drop(columns=["volume"])
        with pytest.raises(ValueError, match="volume"):
            compute_features(df)

    def test_non_positive_prices_raise(self):
        df = make_ohlcv()
        df.loc[5, "close"] = 0.0
        with pytest.raises(ValueError, match="positive"):
            compute_features(df)


class TestNoLookahead:
    def test_truncating_future_does_not_change_past_features(self):
        """The core guarantee: features at bar t depend only on bars <= t."""
        df = make_ohlcv(120)
        full = compute_features(df)
        for cut in (60, 90, 119):
            partial = compute_features(df.iloc[:cut].copy())
            pd.testing.assert_frame_equal(
                full.iloc[:cut].reset_index(drop=True),
                partial.reset_index(drop=True),
                check_exact=False,
                rtol=1e-12,
            )


class TestDeterminism:
    def test_same_input_identical_output(self):
        df = make_ohlcv()
        pd.testing.assert_frame_equal(compute_features(df), compute_features(df))

    def test_golden_log_return(self):
        """log_return_1 at bar t is ln(close_t / close_{t-1}) exactly."""
        df = make_ohlcv(60)
        features = compute_features(df)
        t = 55
        expected = np.log(df["close"].iloc[t] / df["close"].iloc[t - 1])
        assert features["log_return_1"].iloc[t] == pytest.approx(expected, rel=1e-12)

    def test_golden_volume_zscore(self):
        """volume_zscore uses the trailing 20-bar window including bar t."""
        df = make_ohlcv(60)
        features = compute_features(df)
        t = 55
        window = df["volume"].iloc[t - 19 : t + 1]
        expected = (df["volume"].iloc[t] - window.mean()) / window.std(ddof=1)
        assert features["volume_zscore"].iloc[t] == pytest.approx(expected, rel=1e-9)


class TestFeatureProperties:
    def test_rsi_bounded_0_100(self):
        features = compute_features(make_ohlcv(200))
        complete = features[features["complete"]]
        assert complete["rsi_14"].between(0, 100).all()

    def test_atr_positive_on_complete_rows(self):
        features = compute_features(make_ohlcv(200))
        complete = features[features["complete"]]
        assert (complete["atr_14"] > 0).all()

    def test_warmup_rows_marked_incomplete(self):
        features = compute_features(make_ohlcv(120))
        assert not features["complete"].iloc[:WARMUP_BARS].any()
        assert features["complete"].iloc[WARMUP_BARS:].all()

    def test_complete_rows_have_no_nans(self):
        features = compute_features(make_ohlcv(120))
        complete = features[features["complete"]]
        feature_cols = [c for c in FEATURE_COLUMNS]
        assert not complete[feature_cols].isna().any().any()
