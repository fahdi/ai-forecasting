"""Tests for app.services.data_service targeting 100% line coverage.

External I/O is mocked:
- yfinance (no network)
- parquet serialization (no pyarrow/fastparquet in env; stubbed via pickle)
- prometheus metric recording
Real file operations happen inside pytest tmp_path.
"""

import json
import pickle
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import app.services.data_service as ds_mod
from app.core.config import settings
from app.services.data_service import DataService


def make_df(n=10, start="2024-01-01"):
    idx = pd.date_range(start, periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": np.linspace(10, 20, n),
            "high": np.linspace(11, 21, n),
            "low": np.linspace(9, 19, n),
            "close": np.linspace(10.5, 20.5, n),
            "volume": np.arange(n, dtype=float) + 100,
        },
        index=idx,
    )


class FakeUpload:
    """Minimal stand-in for fastapi.UploadFile."""

    def __init__(self, filename, content):
        self.filename = filename
        self._content = content

    async def read(self):
        return self._content


@pytest.fixture
def parquet_stub(monkeypatch):
    """No parquet engine is installed; route parquet I/O through pickle."""
    monkeypatch.setattr(
        pd.DataFrame, "to_parquet", lambda self, path, *a, **k: self.to_pickle(path)
    )
    monkeypatch.setattr(pd, "read_parquet", lambda path, *a, **k: pd.read_pickle(path))


@pytest.fixture
def svc(tmp_path, monkeypatch, parquet_stub):
    monkeypatch.setattr(settings, "DATA_STORAGE_PATH", str(tmp_path / "data"))
    monkeypatch.setattr(ds_mod, "record_data_points_processed", MagicMock())
    return DataService()


def cache_path(svc, symbol, source):
    return f"{svc.data_path}/processed/{symbol}_{source}.parquet"


def write_cache(svc, symbol, source, df):
    df.to_pickle(cache_path(svc, symbol, source))


# ---------------------------------------------------------------------------
# __init__ / _ensure_directories
# ---------------------------------------------------------------------------

def test_init_creates_directories(svc, tmp_path):
    base = tmp_path / "data"
    for sub in ("raw", "processed", "temp"):
        assert (base / sub).is_dir()


# ---------------------------------------------------------------------------
# get_historical_data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_historical_data_cached_with_filters(svc):
    write_cache(svc, "AAPL", "yahoo", make_df(10))
    result = await svc.get_historical_data(
        "AAPL", start_date="2024-01-03", end_date="2024-01-05"
    )
    assert len(result) == 3
    assert result.index.min() >= pd.Timestamp("2024-01-03")


@pytest.mark.asyncio
async def test_get_historical_data_cache_filtered_empty_falls_through(svc):
    write_cache(svc, "AAPL", "yahoo", make_df(5))
    fresh = make_df(4, start="2025-06-01")
    fresh["symbol"] = "AAPL"
    with patch.object(svc, "_fetch_yahoo_data", AsyncMock(return_value=fresh)):
        result = await svc.get_historical_data("AAPL", start_date="2025-01-01")
    assert len(result) == 4
    ds_mod.record_data_points_processed.assert_called_once_with("yahoo", "AAPL", 4)


@pytest.mark.asyncio
async def test_get_historical_data_yahoo_no_cache(svc):
    fresh = make_df(6)
    with patch.object(svc, "_fetch_yahoo_data", AsyncMock(return_value=fresh)):
        result = await svc.get_historical_data("MSFT")
    assert len(result) == 6
    # data was cached for the next call
    assert (await svc._load_cached_data("MSFT", "yahoo")) is not None


@pytest.mark.asyncio
async def test_get_historical_data_empty_result(svc):
    with patch.object(svc, "_fetch_yahoo_data", AsyncMock(return_value=pd.DataFrame())):
        result = await svc.get_historical_data("EMPTY")
    assert result.empty


@pytest.mark.asyncio
async def test_get_historical_data_alpha_vantage_no_key(svc, monkeypatch):
    monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", None)
    result = await svc.get_historical_data("AAPL", source="alpha_vantage")
    assert result.empty


@pytest.mark.asyncio
async def test_get_historical_data_unsupported_source(svc):
    with pytest.raises(ValueError, match="Unsupported data source"):
        await svc.get_historical_data("AAPL", source="quandl")


# ---------------------------------------------------------------------------
# _fetch_yahoo_data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_yahoo_data_default_dates(svc):
    raw = make_df(5).rename(columns=str.title)
    ticker = MagicMock()
    ticker.history.return_value = raw
    with patch.object(ds_mod.yf, "Ticker", return_value=ticker) as ticker_cls:
        result = await svc._fetch_yahoo_data("AAPL")
    ticker_cls.assert_called_once_with("AAPL")
    kwargs = ticker.history.call_args.kwargs
    assert kwargs["start"] and kwargs["end"]  # defaults were filled in
    assert list(result.columns) == ["open", "high", "low", "close", "volume", "symbol"]
    assert (result["symbol"] == "AAPL").all()


@pytest.mark.asyncio
async def test_fetch_yahoo_data_empty_history(svc):
    ticker = MagicMock()
    ticker.history.return_value = pd.DataFrame()
    with patch.object(ds_mod.yf, "Ticker", return_value=ticker):
        result = await svc._fetch_yahoo_data("NONE", "2024-01-01", "2024-02-01")
    assert result.empty


@pytest.mark.asyncio
async def test_fetch_yahoo_data_error_returns_empty(svc):
    with patch.object(ds_mod.yf, "Ticker", side_effect=RuntimeError("network down")):
        result = await svc._fetch_yahoo_data("AAPL")
    assert result.empty


# ---------------------------------------------------------------------------
# _fetch_alpha_vantage_data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_alpha_vantage_with_key_not_implemented(svc, monkeypatch):
    monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "test-key")
    result = await svc._fetch_alpha_vantage_data("AAPL")
    assert result.empty


@pytest.mark.asyncio
async def test_fetch_alpha_vantage_error_returns_empty(svc, monkeypatch):
    class RaisingSettings:
        def __getattr__(self, name):
            raise RuntimeError("settings unavailable")

    monkeypatch.setattr(ds_mod, "settings", RaisingSettings())
    result = await svc._fetch_alpha_vantage_data("AAPL")
    assert result.empty


# ---------------------------------------------------------------------------
# _load_cached_data / _cache_data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_cached_data_missing_returns_none(svc):
    assert await svc._load_cached_data("NOPE", "yahoo") is None


@pytest.mark.asyncio
async def test_load_cached_data_corrupt_returns_none(svc, tmp_path):
    (tmp_path / "data" / "processed" / "BAD_yahoo.parquet").write_bytes(b"not a df")
    assert await svc._load_cached_data("BAD", "yahoo") is None


@pytest.mark.asyncio
async def test_cache_data_error_is_swallowed(svc):
    bad = MagicMock()
    bad.to_parquet.side_effect = OSError("disk full")
    # Must not raise
    await svc._cache_data("AAPL", bad, "yahoo")


# ---------------------------------------------------------------------------
# process_uploaded_file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_uploaded_file_csv(svc, tmp_path):
    df = make_df(5).rename(columns=str.title)
    upload = FakeUpload("prices.csv", df.to_csv().encode())
    result = await svc.process_uploaded_file(upload, "AAPL")
    assert result["rows_processed"] == 5
    assert result["symbol"] == "AAPL"
    assert result["source"] == "custom"
    # processed file written, temp file cleaned up
    assert (tmp_path / "data" / "processed" / "AAPL_custom.parquet").exists()
    assert list((tmp_path / "data" / "temp").iterdir()) == []
    ds_mod.record_data_points_processed.assert_called_once_with("custom", "AAPL", 5)


@pytest.mark.asyncio
async def test_process_uploaded_file_json_with_date_column(svc):
    records = [
        {"date": "2024-01-01", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
        {"date": "2024-01-02", "open": 2, "high": 3, "low": 1.5, "close": 2.5, "volume": 20},
    ]
    upload = FakeUpload("prices.json", json.dumps(records).encode())
    result = await svc.process_uploaded_file(upload, "TSLA")
    assert result["rows_processed"] == 2


@pytest.mark.asyncio
async def test_process_uploaded_file_parquet(svc):
    upload = FakeUpload("prices.parquet", pickle.dumps(make_df(4)))
    result = await svc.process_uploaded_file(upload, "NVDA")
    assert result["rows_processed"] == 4


@pytest.mark.asyncio
async def test_process_uploaded_file_xlsx(svc, monkeypatch):
    monkeypatch.setattr(pd, "read_excel", lambda path, **kwargs: make_df(3))
    upload = FakeUpload("prices.xlsx", b"binary-excel-bytes")
    result = await svc.process_uploaded_file(upload, "GOOG")
    assert result["rows_processed"] == 3


@pytest.mark.asyncio
async def test_process_uploaded_file_unsupported_type(svc):
    upload = FakeUpload("prices.txt", b"whatever")
    with pytest.raises(ValueError, match="Unsupported file type"):
        await svc.process_uploaded_file(upload, "AAPL")


@pytest.mark.asyncio
async def test_process_uploaded_file_missing_columns(svc):
    df = make_df(3).drop(columns=["volume", "close"])
    upload = FakeUpload("prices.csv", df.to_csv().encode())
    with pytest.raises(ValueError, match="Missing required columns"):
        await svc.process_uploaded_file(upload, "AAPL")


# ---------------------------------------------------------------------------
# get_available_symbols
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_available_symbols(svc):
    write_cache(svc, "AAPL", "yahoo", make_df(2))
    write_cache(svc, "MSFT", "custom", make_df(2))
    all_symbols = await svc.get_available_symbols()
    assert sorted(all_symbols) == ["AAPL", "MSFT"]
    yahoo_only = await svc.get_available_symbols(source="yahoo")
    assert yahoo_only == ["AAPL"]


@pytest.mark.asyncio
async def test_get_available_symbols_bad_filename_returns_empty(svc, tmp_path):
    # A parquet file without "_" triggers IndexError -> except path returns []
    (tmp_path / "data" / "processed" / "plain.parquet").write_bytes(b"x")
    assert await svc.get_available_symbols() == []


# ---------------------------------------------------------------------------
# get_data_info
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_data_info_found(svc):
    write_cache(svc, "AAPL", "custom", make_df(5))
    info = await svc.get_data_info("AAPL")
    assert info["symbol"] == "AAPL"
    assert info["source"] == "custom"
    assert info["data_points"] == 5
    assert info["date_range"] == {"start": "2024-01-01", "end": "2024-01-05"}
    assert "close" in info["columns"]


@pytest.mark.asyncio
async def test_get_data_info_missing_returns_none(svc):
    assert await svc.get_data_info("UNKNOWN") is None


@pytest.mark.asyncio
async def test_get_data_info_error_returns_none(svc, tmp_path):
    (tmp_path / "data" / "processed" / "AAPL_yahoo.parquet").write_bytes(b"corrupt")
    assert await svc.get_data_info("AAPL") is None


# ---------------------------------------------------------------------------
# refresh_data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_data_no_new_data(svc):
    with patch.object(svc, "get_historical_data", AsyncMock(return_value=pd.DataFrame())):
        result = await svc.refresh_data("AAPL")
    assert result == {"new_points": 0, "last_updated": None}


@pytest.mark.asyncio
async def test_refresh_data_no_existing(svc):
    fresh = make_df(5)
    with patch.object(svc, "get_historical_data", AsyncMock(return_value=fresh)):
        result = await svc.refresh_data("AAPL")
    assert result["new_points"] == 5
    assert result["last_updated"] is not None
    cached = await svc._load_cached_data("AAPL", "yahoo")
    assert len(cached) == 5


@pytest.mark.asyncio
async def test_refresh_data_merges_with_existing(svc):
    write_cache(svc, "AAPL", "yahoo", make_df(10, start="2024-01-01"))
    overlapping = make_df(10, start="2024-01-06")  # 5 overlap + 5 new
    with patch.object(svc, "get_historical_data", AsyncMock(return_value=overlapping)):
        result = await svc.refresh_data("AAPL")
    assert result["new_points"] == 5
    cached = await svc._load_cached_data("AAPL", "yahoo")
    assert len(cached) == 15
    assert cached.index.is_monotonic_increasing


@pytest.mark.asyncio
async def test_refresh_data_error_propagates(svc):
    with patch.object(
        svc, "get_historical_data", AsyncMock(side_effect=RuntimeError("boom"))
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await svc.refresh_data("AAPL")


# ---------------------------------------------------------------------------
# delete_data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_data_specific_source(svc):
    write_cache(svc, "AAPL", "yahoo", make_df(2))
    assert await svc.delete_data("AAPL", source="yahoo") is True
    assert await svc._load_cached_data("AAPL", "yahoo") is None


@pytest.mark.asyncio
async def test_delete_data_all_sources(svc):
    write_cache(svc, "AAPL", "yahoo", make_df(2))
    write_cache(svc, "AAPL", "custom", make_df(2))
    assert await svc.delete_data("AAPL") is True
    assert await svc.get_available_symbols() == []


@pytest.mark.asyncio
async def test_delete_data_nothing_to_delete(svc):
    assert await svc.delete_data("GHOST") is False


@pytest.mark.asyncio
async def test_delete_data_error_returns_false(svc):
    write_cache(svc, "AAPL", "yahoo", make_df(2))
    with patch.object(ds_mod.os, "remove", side_effect=OSError("locked")):
        assert await svc.delete_data("AAPL", source="yahoo") is False


# ---------------------------------------------------------------------------
# get_data_stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_data_stats(svc, tmp_path):
    write_cache(svc, "AAPL", "yahoo", make_df(5))
    write_cache(svc, "MSFT", "custom", make_df(3))
    processed = tmp_path / "data" / "processed"
    # unreadable parquet with a valid name -> hits inner bare except
    (processed / "BAD_yahoo.parquet").write_bytes(b"junk")
    # underscore-less name -> skipped by the len(parts) >= 2 guard
    (processed / "plain.parquet").write_bytes(b"junk")
    # non-parquet file -> ignored entirely
    (processed / "notes.txt").write_text("ignore me")

    stats = await svc.get_data_stats()
    assert stats["total_symbols"] == 3  # AAPL, MSFT, BAD
    assert stats["total_data_points"] == 8
    assert stats["data_sources"] == {"yahoo": 2, "custom": 1}
    assert stats["last_updated"] is not None
    assert stats["storage_size"] > 0


@pytest.mark.asyncio
async def test_get_data_stats_error_returns_defaults(svc):
    with patch.object(ds_mod.os, "listdir", side_effect=OSError("io error")):
        stats = await svc.get_data_stats()
    assert stats == {
        "total_symbols": 0,
        "total_data_points": 0,
        "data_sources": {},
        "last_updated": None,
        "storage_size": 0,
    }


@pytest.mark.asyncio
async def test_cache_round_trip_uses_real_parquet_engine(tmp_path):
    """Regression: prod image shipped without a parquet engine, so every
    _cache_data call failed (swallowed as best-effort) and the data cache /
    stats stayed empty. Round-trip a real frame with NO mocks so a missing
    pyarrow dependency fails the suite instead of production."""
    import pandas as pd
    from app.services.data_service import DataService

    svc = DataService()
    svc.data_path = str(tmp_path)
    svc._ensure_directories()
    frame = pd.DataFrame(
        {"Open": [1.0, 2.0], "Close": [1.5, 2.5]},
        index=pd.to_datetime(["2026-08-01", "2026-08-02"]),
    )
    await svc._cache_data("TEST-RT", frame, "yahoo")
    loaded = await svc._load_cached_data("TEST-RT", "yahoo")
    assert loaded is not None
    assert len(loaded) == 2
    assert list(loaded["Close"]) == [1.5, 2.5]


# ---------------------------------------------------------------------------
# Cache freshness (TTL) — forecasts must not run on permanently frozen data
# ---------------------------------------------------------------------------

def _write_cache(svc, symbol: str, mtime_offset_seconds: float = 0.0):
    import os
    import time
    import pandas as pd

    frame = pd.DataFrame(
        {"Open": [1.0], "Close": [1.5]},
        index=pd.to_datetime(["2026-08-01"]),
    )
    path = f"{svc.data_path}/processed/{symbol}_yahoo.parquet"
    frame.to_parquet(path)
    if mtime_offset_seconds:
        stamp = time.time() - mtime_offset_seconds
        os.utime(path, (stamp, stamp))
    return frame


@pytest.mark.asyncio
async def test_fresh_cache_is_served_without_fetching(tmp_path):
    from unittest.mock import AsyncMock, patch
    from app.services.data_service import DataService

    svc = DataService()
    svc.data_path = str(tmp_path)
    svc._ensure_directories()
    _write_cache(svc, "FRESH")
    with patch.object(svc, "_fetch_yahoo_data", new=AsyncMock()) as fetch:
        result = await svc.get_historical_data("FRESH")
    fetch.assert_not_awaited()
    assert len(result) == 1


@pytest.mark.asyncio
async def test_stale_cache_triggers_refetch(tmp_path):
    import pandas as pd
    from unittest.mock import AsyncMock, patch
    from app.services.data_service import DataService

    svc = DataService()
    svc.data_path = str(tmp_path)
    svc._ensure_directories()
    _write_cache(svc, "STALE", mtime_offset_seconds=3 * 24 * 3600)
    fresh = pd.DataFrame(
        {"Open": [2.0], "Close": [2.5]},
        index=pd.to_datetime(["2026-08-04"]),
    )
    with patch.object(svc, "_fetch_yahoo_data", new=AsyncMock(return_value=fresh)) as fetch:
        result = await svc.get_historical_data("STALE")
    fetch.assert_awaited_once()
    assert list(result["Close"]) == [2.5]


@pytest.mark.asyncio
async def test_stale_cache_survives_failed_refetch(tmp_path):
    """Availability fallback: a Yahoo outage must not kill forecasts when we
    still hold stale-but-usable history."""
    from unittest.mock import AsyncMock, patch
    from app.services.data_service import DataService

    svc = DataService()
    svc.data_path = str(tmp_path)
    svc._ensure_directories()
    _write_cache(svc, "FALLBACK", mtime_offset_seconds=3 * 24 * 3600)
    with patch.object(svc, "_fetch_yahoo_data", new=AsyncMock(side_effect=RuntimeError("yahoo down"))):
        result = await svc.get_historical_data("FALLBACK")
    assert list(result["Close"]) == [1.5]


@pytest.mark.asyncio
async def test_stale_cache_survives_empty_refetch(tmp_path):
    import pandas as pd
    from unittest.mock import AsyncMock, patch
    from app.services.data_service import DataService

    svc = DataService()
    svc.data_path = str(tmp_path)
    svc._ensure_directories()
    _write_cache(svc, "EMPTYF", mtime_offset_seconds=3 * 24 * 3600)
    with patch.object(svc, "_fetch_yahoo_data", new=AsyncMock(return_value=pd.DataFrame())):
        result = await svc.get_historical_data("EMPTYF")
    assert list(result["Close"]) == [1.5]
