"""
Tests for app.models.feature_engineer.

A single full engineer_features() run over ~280 synthetic OHLCV rows covers
every indicator branch (the default FEATURE_CONFIG enables all of them and
the longest lookback is 200 bars + warmup). Error branches are hit by calling
the private builders with malformed frames: each one catches, logs, and
returns the frame untouched.
"""

import numpy as np
import pandas as pd
import pytest

from app.models.feature_engineer import FeatureEngineer


def make_ohlcv(n=280, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    close = 100.0 + np.cumsum(rng.normal(0.05, 1.0, n))
    close = np.abs(close) + 50.0
    close[10] = close[9]  # flat step so OBV's "unchanged" branch runs
    open_ = close * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    volume = rng.integers(1_000, 5_000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


@pytest.fixture
def engineer():
    return FeatureEngineer()


class TestEngineerFeatures:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, engineer):
        data = make_ohlcv()
        result = await engineer.engineer_features(data)

        # 200-bar lookbacks eat the head, the rest must survive dropna
        assert len(result) > 0
        assert not result.isna().any().any()

        expected = [
            "sma_20", "price_sma_20_ratio", "ema_10", "price_ema_10_ratio",
            "rsi", "macd", "macd_signal", "macd_histogram",
            "bb_upper", "bb_lower", "bb_middle", "bb_width", "bb_position",
            "stoch_k", "stoch_d", "williams_r", "cci", "adx",
            "close_lag_1", "volume_lag_5", "return_lag_10",
            "close_rolling_mean_5", "close_rolling_std_20",
            "close_rolling_min_50", "close_rolling_max_10",
            "volume_rolling_mean_5", "volume_rolling_std_10", "volatility_20",
            "day_of_week", "day_of_month", "month", "quarter", "year",
            "is_month_end", "is_quarter_end", "is_year_end",
            "realized_volatility_10", "price_change", "price_change_pct",
            "hl_spread", "hl_spread_pct", "oc_spread", "oc_spread_pct",
            "price_position", "momentum_5", "volume_change",
            "volume_change_pct", "volume_sma_20", "volume_ratio_20",
            "volume_price_trend", "obv",
        ]
        for col in expected:
            assert col in result.columns, col

        # column names were normalised to lowercase, source untouched
        assert {"open", "high", "low", "close", "volume"} <= set(result.columns)
        assert list(data.columns) == ["Open", "High", "Low", "Close", "Volume"]

        # sanity on well-known ranges
        assert result["rsi"].between(0, 100).all()
        assert result["stoch_k"].between(0, 100).all()
        assert result["williams_r"].between(-100, 0).all()
        assert (result["bb_upper"] >= result["bb_lower"]).all()
        assert result["price_position"].between(0, 1).all()

    @pytest.mark.asyncio
    async def test_missing_columns_raises(self, engineer):
        data = make_ohlcv().drop(columns=["Volume", "High"])
        with pytest.raises(ValueError, match="Missing required columns"):
            await engineer.engineer_features(data)

    def test_config_driven_attributes(self, engineer):
        assert "sma" in engineer.technical_indicators
        assert 1 in engineer.lag_features
        assert 5 in engineer.rolling_windows


class TestBuilderErrorPaths:
    """Each private builder swallows errors and returns the frame unchanged."""

    @pytest.mark.parametrize(
        "method",
        [
            "_add_technical_indicators",
            "_add_lag_features",
            "_add_rolling_statistics",
            "_add_volatility_features",
            "_add_price_features",
            "_add_volume_features",
        ],
    )
    def test_missing_columns_returned_unchanged(self, engineer, method):
        bad = pd.DataFrame({"unrelated": [1.0, 2.0, 3.0]})
        out = getattr(engineer, method)(bad.copy())
        assert list(out.columns) == ["unrelated"]

    def test_calendar_features_bad_index_returned_unchanged(self, engineer):
        bad = pd.DataFrame({"close": [1.0]}, index=["definitely-not-a-date"])
        out = engineer._add_calendar_features(bad.copy())
        assert "day_of_week" not in out.columns


class TestCalendarFeatures:
    def test_converts_string_index(self, engineer):
        df = pd.DataFrame(
            {"close": [1.0, 2.0]}, index=["2024-03-31", "2024-12-31"]
        )
        out = engineer._add_calendar_features(df)
        assert isinstance(out.index, pd.DatetimeIndex)
        assert out["quarter"].tolist() == [1, 4]
        assert out["is_quarter_end"].tolist() == [1, 1]
        assert out["is_year_end"].tolist() == [0, 1]
        assert out["is_month_end"].tolist() == [1, 1]
        assert out["year"].tolist() == [2024, 2024]


class TestIndicatorMath:
    def test_rsi_extremes(self, engineer):
        rising = pd.Series(np.arange(1.0, 31.0))
        rsi = engineer._calculate_rsi(rising)
        assert rsi.iloc[-1] == pytest.approx(100.0)

        falling = pd.Series(np.arange(31.0, 1.0, -1.0))
        assert engineer._calculate_rsi(falling).iloc[-1] == pytest.approx(0.0)

    def test_macd_histogram_is_difference(self, engineer):
        prices = pd.Series(np.linspace(100, 130, 60))
        out = engineer._calculate_macd(prices)
        pd.testing.assert_series_equal(
            out["histogram"], out["macd"] - out["signal"], check_names=False
        )

    def test_bollinger_band_geometry(self, engineer):
        prices = pd.Series(100 + np.sin(np.linspace(0, 12, 80)) * 5)
        out = engineer._calculate_bollinger_bands(prices)
        valid = slice(19, None)
        assert (out["upper"][valid] >= out["middle"][valid]).all()
        assert (out["middle"][valid] >= out["lower"][valid]).all()
        expected_width = (out["upper"] - out["lower"]) / out["middle"]
        pd.testing.assert_series_equal(out["width"], expected_width, check_names=False)

    def test_stochastic_range(self, engineer):
        df = make_ohlcv(n=60).rename(columns=str.lower)
        out = engineer._calculate_stochastic(df)
        assert out["k"].dropna().between(0, 100).all()
        assert out["d"].dropna().between(0, 100).all()

    def test_williams_r_range(self, engineer):
        df = make_ohlcv(n=60).rename(columns=str.lower)
        wr = engineer._calculate_williams_r(df)
        assert wr.dropna().between(-100, 0).all()

    def test_cci_finite(self, engineer):
        df = make_ohlcv(n=60).rename(columns=str.lower)
        cci = engineer._calculate_cci(df)
        assert np.isfinite(cci.dropna()).all()
        assert len(cci.dropna()) > 0

    def test_adx_positive(self, engineer):
        df = make_ohlcv(n=60).rename(columns=str.lower)
        adx = engineer._calculate_adx(df)
        assert (adx.dropna() > 0).all()

    def test_obv_up_down_flat(self, engineer):
        df = pd.DataFrame(
            {
                "close": [10.0, 11.0, 9.0, 9.0],
                "volume": [100.0, 200.0, 300.0, 400.0],
            }
        )
        obv = engineer._calculate_obv(df)
        # start, +200 on up, -300 on down, unchanged on flat
        assert obv.tolist() == [100.0, 300.0, 0.0, 0.0]
