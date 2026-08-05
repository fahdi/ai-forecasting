"""
Parkinson range volatility (app.models.feature_engineer).

Parkinson and Garman-Klass were both commented out of the feature set with a
"TODO: Fix syntax error" note, so the forecast model only ever saw
close-to-close realized volatility and nothing about intrabar range.

Only Parkinson is wired in. Both were measured on real 4h bars for BTC, ETH
and SOL; they score the same within noise but correlate .992, and carrying
both made out-of-sample R^2 worse than either alone on all three pairs. The
module comment records the numbers.

The estimator has a closed form, so these tests pin the math against
analytically known answers rather than against whatever the code returns.
"""

import numpy as np
import pandas as pd
import pytest

from app.models.feature_engineer import FeatureEngineer, parkinson_volatility

LN2 = np.log(2.0)


def _bars(n, high_low_ratio=2.0, close=100.0):
    """Synthetic OHLC where every bar has the same log-range."""
    low = close / np.sqrt(high_low_ratio)
    return pd.DataFrame(
        {
            "open": np.full(n, close),
            "high": np.full(n, low * high_low_ratio),
            "low": np.full(n, low),
            "close": np.full(n, close),
        }
    )


class TestParkinsonMath:
    def test_constant_range_matches_closed_form(self):
        """sigma_P = |ln(H/L)| / (2*sqrt(ln 2)) when every bar is identical."""
        df = _bars(50, high_low_ratio=2.0)
        result = parkinson_volatility(df["high"], df["low"], window=20)
        assert result.iloc[-1] == pytest.approx(LN2 / (2.0 * np.sqrt(LN2)), rel=1e-12)

    def test_averages_variance_before_taking_the_root(self):
        """sqrt(mean(var)) != mean(sqrt(var)) once bars stop being identical.

        Half the window is wide-range and half is narrow, which makes the two
        orderings numerically distinguishable. This pins the correct one.
        """
        df = pd.concat(
            [_bars(10, high_low_ratio=2.0), _bars(10, high_low_ratio=1.10)],
            ignore_index=True,
        )
        result = parkinson_volatility(df["high"], df["low"], window=20).iloc[-1]

        factor = 1.0 / (4.0 * LN2)
        var_wide = factor * np.log(2.0) ** 2
        var_narrow = factor * np.log(1.10) ** 2
        correct = np.sqrt((10 * var_wide + 10 * var_narrow) / 20)
        wrong = (10 * np.sqrt(var_wide) + 10 * np.sqrt(var_narrow)) / 20

        assert result == pytest.approx(correct, rel=1e-12)
        assert abs(result - wrong) > 1e-4

    def test_zero_range_bars_have_zero_volatility(self):
        df = _bars(30, high_low_ratio=1.0)
        result = parkinson_volatility(df["high"], df["low"], window=20)
        assert result.iloc[-1] == pytest.approx(0.0, abs=1e-15)

    def test_wider_range_means_higher_volatility(self):
        narrow, wide = _bars(50, 1.05), _bars(50, 1.50)
        assert (
            parkinson_volatility(wide["high"], wide["low"], window=20).iloc[-1]
            > parkinson_volatility(narrow["high"], narrow["low"], window=20).iloc[-1]
        )

    def test_warmup_rows_are_nan_not_zero(self):
        """A partially-filled window must not look like a calm market."""
        result = parkinson_volatility(_bars(30)["high"], _bars(30)["low"], window=20)
        assert result.iloc[:19].isna().all()
        assert result.iloc[19:].notna().all()


class TestWiredIntoFeatureSet:
    """The estimator is only worth anything if the model actually sees it,
    which is exactly what the commented-out code failed to do."""

    def _ohlcv(self, n=120, seed=11):
        rng = np.random.default_rng(seed)
        close = 100 + np.cumsum(rng.normal(0, 1, n))
        return pd.DataFrame(
            {
                "open": close + rng.normal(0, 0.2, n),
                "high": close + np.abs(rng.normal(1, 0.3, n)),
                "low": close - np.abs(rng.normal(1, 0.3, n)),
                "close": close,
                "volume": rng.integers(1000, 5000, n).astype(float),
            },
            index=pd.date_range("2024-01-01", periods=n, freq="D"),
        )

    def test_engineer_emits_the_column(self):
        out = FeatureEngineer()._add_volatility_features(self._ohlcv())
        assert "parkinson_volatility" in out.columns
        assert out["parkinson_volatility"].iloc[-1] > 0

    def test_garman_klass_stays_out_of_the_feature_set(self):
        """Collinear with Parkinson and measurably worse when both are carried.
        Re-adding it should be a deliberate, evidence-backed change."""
        out = FeatureEngineer()._add_volatility_features(self._ohlcv())
        assert "garman_klass_volatility" not in out.columns
