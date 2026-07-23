"""
Deterministic feature engineering for crypto OHLCV bars (PRD §4.1 R4).

Pure function API: `compute_features(ohlcv)` takes an OHLCV DataFrame and
returns a feature DataFrame. No I/O. Every feature at bar t is computed
exclusively from bars <= t (no lookahead) — enforced by tests that truncate
the future and require identical past values.
"""

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]

# Bars of history required before every feature is well-defined and warmed up.
# Driven by the longest window used (EMA 50).
WARMUP_BARS = 50

FEATURE_COLUMNS = [
    "log_return_1",
    "log_return_3",
    "log_return_7",
    "ema_12_ratio",
    "ema_26_ratio",
    "ema_50_ratio",
    "rsi_14",
    "atr_14",
    "volatility_20",
    "volume_zscore",
    "log_return_1_lag1",
    "log_return_1_lag2",
    "log_return_1_lag3",
]


def _validate(ohlcv: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in ohlcv.columns]
    if missing:
        raise ValueError(f"OHLCV frame missing required columns: {missing}")
    prices = ohlcv[["open", "high", "low", "close"]]
    if not (prices > 0).all().all():
        raise ValueError("All prices must be positive")


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder smoothing: recursive EMA with alpha=1/period — strictly causal.
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    # All-gain windows (avg_loss == 0) are maximally overbought.
    return rsi.fillna(100.0).where(delta.notna(), np.nan)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, adjust=False).mean()


def compute_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Compute the v1 feature set from an OHLCV frame ordered by open_time.

    Returns a frame with one row per input bar: `open_time`, all
    FEATURE_COLUMNS, and a `complete` flag that is False for warm-up rows
    (insufficient history — marked, never silently filled).
    """
    _validate(ohlcv)
    df = ohlcv.sort_values("open_time").reset_index(drop=True)
    close, volume = df["close"], df["volume"]

    features = pd.DataFrame({"open_time": df["open_time"]})
    log_close = np.log(close)
    features["log_return_1"] = log_close.diff(1)
    features["log_return_3"] = log_close.diff(3)
    features["log_return_7"] = log_close.diff(7)

    for span in (12, 26, 50):
        ema = close.ewm(span=span, adjust=True).mean()
        features[f"ema_{span}_ratio"] = close / ema

    features["rsi_14"] = _rsi(close, 14)
    features["atr_14"] = _atr(df["high"], df["low"], close, 14)
    features["volatility_20"] = features["log_return_1"].rolling(20).std(ddof=1)

    vol_mean = volume.rolling(20).mean()
    vol_std = volume.rolling(20).std(ddof=1)
    features["volume_zscore"] = (volume - vol_mean) / vol_std

    for lag in (1, 2, 3):
        features[f"log_return_1_lag{lag}"] = features["log_return_1"].shift(lag)

    features["complete"] = features.index >= WARMUP_BARS
    return features
