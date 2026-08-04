"""
Line-coverage tests for the data / health / models endpoint modules plus a few
straggler lines in ensemble_predictor, kline_stream and signal_service.

All external effects (yfinance, redis, model training, websockets) are mocked;
the suite is hermetic and uses the sqlite DATABASE_URL set up by conftest.py.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.database import get_db
import app.api.v1.endpoints.data as data_ep
import app.api.v1.endpoints.health as health_ep
import app.api.v1.endpoints.models as models_ep


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def data_service():
    """DataService mocked out in the data endpoint module namespace."""
    with mock.patch.object(data_ep, "DataService") as cls:
        yield cls.return_value


@pytest.fixture
def model_service():
    """ModelService mocked out in the models endpoint module namespace."""
    with mock.patch.object(models_ep, "ModelService") as cls:
        yield cls.return_value


# ---------------------------------------------------------------------------
# data.py
# ---------------------------------------------------------------------------

def test_upload_success(client, data_service):
    data_service.process_uploaded_file = mock.AsyncMock(
        return_value={"file_id": "f-1", "rows_processed": 10}
    )
    resp = client.post(
        "/api/v1/data/upload",
        files={"file": ("prices.csv", b"a,b\n1,2\n", "text/csv")},
        data={"symbol": "aapl"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["rows_processed"] == 10
    assert body["status"] == "success"


def test_upload_rejects_extension(client, data_service):
    resp = client.post(
        "/api/v1/data/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"symbol": "AAPL"},
    )
    # The endpoint's blanket `except Exception` swallows the 400 HTTPException
    # and re-raises it as a 500 (bug noted in report).
    assert resp.status_code == 500
    assert "File type not supported" in resp.json()["detail"]


def test_upload_rejects_oversized(client, data_service, monkeypatch):
    monkeypatch.setattr(settings, "MAX_FILE_SIZE", 1)
    resp = client.post(
        "/api/v1/data/upload",
        files={"file": ("prices.csv", b"a,b\n1,2\n", "text/csv")},
        data={"symbol": "AAPL"},
    )
    assert resp.status_code == 500
    assert "File too large" in resp.json()["detail"]


def test_symbols_success_and_error(client, data_service):
    data_service.get_available_symbols = mock.AsyncMock(
        return_value=["AAPL", "MSFT"]
    )
    resp = client.get("/api/v1/data/symbols", params={"source": "yahoo"})
    assert resp.status_code == 200
    assert resp.json() == {"symbols": ["AAPL", "MSFT"], "total_count": 2}

    data_service.get_available_symbols = mock.AsyncMock(
        side_effect=RuntimeError("db down")
    )
    resp = client.get("/api/v1/data/symbols")
    assert resp.status_code == 500


def test_data_info_success(client, data_service):
    data_service.get_data_info = mock.AsyncMock(
        return_value={
            "symbol": "AAPL",
            "source": "yahoo",
            "last_updated": datetime(2026, 1, 2, 3, 4, 5),
            "data_points": 100,
            "date_range": {"start": "2025-01-01", "end": "2026-01-01"},
            "columns": ["open", "close"],
        }
    )
    resp = client.get("/api/v1/data/info/aapl")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "AAPL"


def test_data_info_not_found(client, data_service):
    data_service.get_data_info = mock.AsyncMock(return_value=None)
    resp = client.get("/api/v1/data/info/none")
    # 404 swallowed by the blanket except -> 500 (bug noted in report)
    assert resp.status_code == 500


@pytest.fixture
def download_env(client, data_service, tmp_path, monkeypatch):
    """Downloads write to a relative temp/ dir; run them from tmp_path."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "temp").mkdir()
    frame = pd.DataFrame(
        {"open": [1.0, 2.0], "close": [1.5, 2.5]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    data_service.get_historical_data = mock.AsyncMock(return_value=frame)
    return data_service


def test_download_csv(client, download_env):
    resp = client.get("/api/v1/data/download/aapl", params={"format": "csv"})
    assert resp.status_code == 200
    assert "close" in resp.text


def test_download_json(client, download_env):
    resp = client.get("/api/v1/data/download/aapl", params={"format": "JSON"})
    assert resp.status_code == 200
    assert json.loads(resp.text)


def test_download_parquet(client, data_service, tmp_path, monkeypatch):
    # pyarrow is not installed, so hand the endpoint a frame-like object whose
    # to_parquet writes a real file (FileResponse needs one on disk).
    monkeypatch.chdir(tmp_path)
    (tmp_path / "temp").mkdir()
    fake = mock.MagicMock()
    fake.empty = False
    fake.to_parquet.side_effect = (
        lambda path, index=True: open(path, "wb").write(b"PAR1")
    )
    data_service.get_historical_data = mock.AsyncMock(return_value=fake)
    resp = client.get("/api/v1/data/download/aapl", params={"format": "parquet"})
    assert resp.status_code == 200
    assert resp.content == b"PAR1"


def test_download_bad_format(client, download_env):
    resp = client.get("/api/v1/data/download/aapl", params={"format": "xml"})
    assert resp.status_code == 500
    assert "Unsupported format" in resp.json()["detail"]


def test_download_no_data(client, data_service):
    data_service.get_historical_data = mock.AsyncMock(
        return_value=pd.DataFrame()
    )
    resp = client.get("/api/v1/data/download/none")
    assert resp.status_code == 500
    assert "No data found" in resp.json()["detail"]


def test_refresh_success_and_error(client, data_service):
    data_service.refresh_data = mock.AsyncMock(
        return_value={"new_points": 5, "last_updated": "2026-07-25T00:00:00"}
    )
    resp = client.post("/api/v1/data/refresh/aapl")
    assert resp.status_code == 200
    assert resp.json()["new_data_points"] == 5

    data_service.refresh_data = mock.AsyncMock(
        side_effect=RuntimeError("yahoo down")
    )
    resp = client.post("/api/v1/data/refresh/aapl")
    assert resp.status_code == 500


def test_delete_data_success_and_missing(client, data_service):
    data_service.delete_data = mock.AsyncMock(return_value=True)
    resp = client.delete("/api/v1/data/AAPL")
    assert resp.status_code == 200
    assert "deleted successfully" in resp.json()["message"]

    data_service.delete_data = mock.AsyncMock(return_value=False)
    resp = client.delete("/api/v1/data/NONE")
    assert resp.status_code == 500  # 404 swallowed by blanket except


def test_data_sources(client):
    resp = client.get("/api/v1/data/sources")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()["sources"]]
    assert names == ["yahoo", "alpha_vantage", "custom"]


def test_data_stats_success_and_error(client, data_service):
    data_service.get_data_stats = mock.AsyncMock(
        return_value={
            "total_symbols": 3,
            "total_data_points": 1000,
            "data_sources": ["yahoo"],
            "last_updated": "2026-07-25T00:00:00",
            "storage_size": 12345,
        }
    )
    resp = client.get("/api/v1/data/stats")
    assert resp.status_code == 200
    assert resp.json()["total_symbols"] == 3

    data_service.get_data_stats = mock.AsyncMock(
        side_effect=RuntimeError("boom")
    )
    resp = client.get("/api/v1/data/stats")
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# health.py
# ---------------------------------------------------------------------------

class _FakeResult:
    async def fetchone(self):
        return (1,)


class _GoodDB:
    async def execute(self, query):
        return _FakeResult()


class _BadDB:
    async def execute(self, query):
        raise RuntimeError("no database")


def _override_db(db):
    async def _dep():
        yield db
    app.dependency_overrides[get_db] = _dep


def test_health_basic_ready_live(client):
    for path, status in [("/", "healthy"), ("/ready", "ready"),
                         ("/live", "alive")]:
        resp = client.get(f"/api/v1/health{path}")
        assert resp.status_code == 200
        assert resp.json()["status"] == status


def test_detailed_health_all_healthy(client, tmp_path, monkeypatch):
    _override_db(_GoodDB())
    redis_mod = mock.MagicMock()
    redis_mod.from_url.return_value = mock.AsyncMock()
    monkeypatch.setattr(health_ep, "redis", redis_mod)
    monkeypatch.setattr(settings, "DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "MODEL_STORAGE_PATH", str(tmp_path))

    resp = client.get("/api/v1/health/detailed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    for component in ("database", "redis", "storage", "model_storage",
                      "ml_libraries"):
        assert body["components"][component]["status"] == "healthy"
    assert "pandas" in body["components"]["ml_libraries"]["versions"]


def test_detailed_health_all_degraded(client, tmp_path, monkeypatch):
    _override_db(_BadDB())
    redis_mod = mock.MagicMock()
    redis_mod.from_url.side_effect = ConnectionError("no redis")
    monkeypatch.setattr(health_ep, "redis", redis_mod)
    missing = str(tmp_path / "does-not-exist")
    monkeypatch.setattr(settings, "DATA_STORAGE_PATH", missing)
    monkeypatch.setattr(settings, "MODEL_STORAGE_PATH", missing)
    # `import xgboost` inside the endpoint raises when the sys.modules entry
    # is None -> drives the ml_libraries except branch.
    monkeypatch.setitem(sys.modules, "xgboost", None)

    resp = client.get("/api/v1/health/detailed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    for component in ("database", "redis", "storage", "model_storage",
                      "ml_libraries"):
        assert body["components"][component]["status"] == "unhealthy"


def test_detailed_health_storage_check_raises(client, monkeypatch):
    _override_db(_GoodDB())
    redis_mod = mock.MagicMock()
    redis_mod.from_url.return_value = mock.AsyncMock()
    monkeypatch.setattr(health_ep, "redis", redis_mod)

    sentinel = "/__coverage_sentinel_path__"
    monkeypatch.setattr(settings, "DATA_STORAGE_PATH", sentinel)
    monkeypatch.setattr(settings, "MODEL_STORAGE_PATH", sentinel)
    real_exists = os.path.exists

    def exploding_exists(path):
        if path == sentinel:
            raise RuntimeError("stat blew up")
        return real_exists(path)

    monkeypatch.setattr(os.path, "exists", exploding_exists)

    resp = client.get("/api/v1/health/detailed")
    assert resp.status_code == 200
    body = resp.json()
    assert "Storage check failed" in body["components"]["storage"]["message"]
    assert ("Model storage check failed"
            in body["components"]["model_storage"]["message"])


# ---------------------------------------------------------------------------
# models.py
# ---------------------------------------------------------------------------

def test_get_health_engine_without_database_url(monkeypatch):
    monkeypatch.setattr(models_ep, "_HEALTH_ENGINE", "unset")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert models_ep.get_health_engine() is None
    # Memoized: second call returns the cached None without re-checking env.
    assert models_ep.get_health_engine() is None


def test_get_health_engine_builds_and_memoizes(monkeypatch):
    monkeypatch.setattr(models_ep, "_HEALTH_ENGINE", "unset")
    engine = models_ep.get_health_engine()  # DATABASE_URL is conftest sqlite
    assert engine is not None
    assert models_ep.get_health_engine() is engine
    engine.dispose()


def test_models_health_no_engine(client):
    app.dependency_overrides[models_ep.get_health_engine] = lambda: None
    resp = client.get("/api/v1/models/health")
    assert resp.status_code == 200
    assert resp.json() == {"pairs": []}


def test_models_health_with_engine(client, monkeypatch):
    monkeypatch.setattr(models_ep, "_HEALTH_ENGINE", "unset")
    engine = models_ep.get_health_engine()
    app.dependency_overrides[models_ep.get_health_engine] = lambda: engine
    resp = client.get("/api/v1/models/health")
    assert resp.status_code == 200
    assert resp.json() == {"pairs": []}
    engine.dispose()


def test_train_model_success_runs_background_task(client, model_service):
    model_service.train_model = mock.AsyncMock(
        return_value={
            "version": "v1",
            "mape": 1.0,
            "mae": 2.0,
            "rmse": 3.0,
            "directional_accuracy": 0.6,
            "metadata": {"k": "v"},
            "performance": {"mape": 1.0},
        }
    )
    # save_model_performance is mocked because the call site passes
    # `metadata=` while the function signature is `model_metadata=`
    # (bug noted in report) — the real call would raise TypeError.
    with mock.patch.object(
        models_ep, "save_model_performance", new=mock.AsyncMock()
    ) as save:
        resp = client.post(
            "/api/v1/models/train",
            json={"symbol": "aapl", "model_type": "ensemble"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["job_id"]
    # TestClient runs the background task synchronously with the request.
    model_service.train_model.assert_awaited_once()
    save.assert_awaited_once()


def test_train_model_background_failure(client, model_service):
    model_service.train_model = mock.AsyncMock(
        side_effect=RuntimeError("training exploded")
    )
    with pytest.raises(RuntimeError, match="training exploded"):
        client.post(
            "/api/v1/models/train",
            json={"symbol": "aapl", "model_type": "xgboost"},
        )


def test_train_model_endpoint_error(client):
    from fastapi import BackgroundTasks

    with mock.patch.object(
        BackgroundTasks, "add_task", side_effect=RuntimeError("queue full")
    ):
        resp = client.post("/api/v1/models/train", json={"symbol": "AAPL"})
    assert resp.status_code == 500


def _seed_performance_row():
    from app.core.database import AsyncSessionLocal, save_model_performance

    async def _seed():
        async with AsyncSessionLocal() as db:
            await save_model_performance(
                db=db,
                model_type="ensemble",
                symbol="COVSYM",
                version="v1",
                mape=1.0,
                mae=2.0,
                rmse=3.0,
                directional_accuracy=0.55,
            )

    asyncio.run(_seed())


def test_get_model_performance(client):
    _seed_performance_row()
    resp = client.get(
        "/api/v1/models/performance",
        params={"symbol": "covsym", "model_type": "ensemble"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] >= 1
    assert body["performances"][0]["symbol"] == "COVSYM"


def test_get_model_performance_error(client):
    _override_db(_BadDB())
    resp = client.get("/api/v1/models/performance")
    assert resp.status_code == 500


def test_list_models_success_and_error(client, model_service):
    model_service.list_models = mock.AsyncMock(
        return_value=[
            {
                "model_type": "ensemble",
                "symbol": "AAPL",
                "version": "v1",
                "last_trained": datetime(2026, 1, 1),
                "performance": {"mape": 1.0},
                "file_size": 123,
            }
        ]
    )
    resp = client.get("/api/v1/models/list")
    assert resp.status_code == 200
    assert resp.json()["total_count"] == 1

    model_service.list_models = mock.AsyncMock(
        side_effect=RuntimeError("fs error")
    )
    resp = client.get("/api/v1/models/list")
    assert resp.status_code == 500


def test_delete_model_success_and_missing(client, model_service):
    model_service.delete_model = mock.AsyncMock(return_value=True)
    resp = client.delete("/api/v1/models/ensemble/aapl")
    assert resp.status_code == 200
    assert "deleted successfully" in resp.json()["message"]

    model_service.delete_model = mock.AsyncMock(return_value=False)
    resp = client.delete("/api/v1/models/ensemble/none")
    assert resp.status_code == 500  # 404 swallowed by blanket except


def test_model_info_success_and_missing(client, model_service):
    model_service.get_model_info = mock.AsyncMock(
        return_value={"model_type": "ensemble", "symbol": "AAPL"}
    )
    resp = client.get("/api/v1/models/ensemble/aapl/info")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "AAPL"

    model_service.get_model_info = mock.AsyncMock(return_value=None)
    resp = client.get("/api/v1/models/ensemble/none/info")
    assert resp.status_code == 500  # 404 swallowed by blanket except


# ---------------------------------------------------------------------------
# Stragglers: ensemble_predictor, kline_stream, signal_service
# ---------------------------------------------------------------------------

class _FakeMember:
    def predict_proba(self, X):
        return np.tile([0.25, 0.75], (len(X), 1))


def test_ensemble_predictor_prob_long_series():
    from app.models.ensemble_predictor import EnsemblePredictor

    predictor = EnsemblePredictor("v1", {"m": _FakeMember()}, ["f1"])
    series = predictor.prob_long_series(pd.DataFrame({"f1": [1.0, 2.0]}))
    assert series.shape == (2,)
    assert np.allclose(series, 0.75)


def test_load_active_registry_without_active_version(tmp_path):
    from app.models.ensemble_predictor import load_active

    (tmp_path / "registry.json").write_text(json.dumps({"active": None}))
    assert load_active(tmp_path) is None


def test_kline_stream_heartbeat_rate_limited():
    from app.services.kline_stream import KlineStreamConsumer

    beats = []
    consumer = KlineStreamConsumer(
        engine=None,
        pairs=["BTCUSDT"],
        interval="4h",
        connect=lambda: None,
        heartbeat_fn=lambda: beats.append(1),
        heartbeat_interval=60.0,
    )
    consumer._maybe_heartbeat()
    consumer._maybe_heartbeat()  # within the interval -> early return
    assert beats == [1]


def test_candle_source_protocol_body():
    from app.services.signal_service import CandleSource

    # The Protocol method body (docstring + Ellipsis) is executable code.
    assert CandleSource.get_recent_candles(object(), "BTCUSDT", "4h", 1) is None


# ---------------------------------------------------------------------------
# ensemble_predictor.py — remaining lines
# ---------------------------------------------------------------------------

def test_ensemble_predictor_prob_long_and_votes():
    from app.models.ensemble_predictor import EnsemblePredictor

    predictor = EnsemblePredictor("v1", {"m": _FakeMember()}, ["f1"])
    row = pd.DataFrame({"f1": [1.0]})
    assert predictor.prob_long(row) == pytest.approx(0.75)
    assert predictor.member_votes(row) == {"m": "long"}


def test_load_active_no_registry_file(tmp_path):
    from app.models.ensemble_predictor import load_active

    assert load_active(tmp_path) is None


def test_load_active_version_without_artifacts(tmp_path):
    from app.models.ensemble_predictor import load_active

    (tmp_path / "registry.json").write_text(json.dumps({"active": "v1"}))
    artifact_dir = tmp_path / "v1"
    artifact_dir.mkdir()
    (artifact_dir / "manifest.json").write_text(
        json.dumps({"feature_columns": ["f1"]})
    )
    assert load_active(tmp_path) is None  # no *.joblib files


def test_load_active_full_round_trip(tmp_path):
    import joblib

    from app.models.ensemble_predictor import load_active

    (tmp_path / "registry.json").write_text(json.dumps({"active": "v1"}))
    artifact_dir = tmp_path / "v1"
    artifact_dir.mkdir()
    (artifact_dir / "manifest.json").write_text(
        json.dumps({"feature_columns": ["f1"]})
    )
    joblib.dump(_FakeMember(), artifact_dir / "member.joblib")

    predictor = load_active(tmp_path)
    assert predictor is not None
    assert predictor.version_id == "v1"
    assert predictor.prob_long(pd.DataFrame({"f1": [1.0]})) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# kline_stream.py — remaining lines
# ---------------------------------------------------------------------------

import app.services.kline_stream as kline_stream_mod
from app.services.kline_stream import KlineStreamConsumer, binance_connect_factory


def _kline_message(closed=True, symbol="BTCUSDT"):
    open_ms = int(pd.Timestamp("2026-07-01", tz="UTC").timestamp() * 1000)
    close_ms = open_ms + 4 * 3600 * 1000 - 1
    return json.dumps(
        {
            "data": {
                "k": {
                    "s": symbol,
                    "t": open_ms,
                    "T": close_ms,
                    "o": "100",
                    "h": "101",
                    "l": "99",
                    "c": "100.5",
                    "v": "12.5",
                    "x": closed,
                }
            }
        }
    )


def _consumer(**kwargs):
    kwargs.setdefault("engine", None)
    kwargs.setdefault("pairs", ["BTCUSDT"])
    kwargs.setdefault("interval", "4h")
    kwargs.setdefault("connect", lambda: None)
    return KlineStreamConsumer(**kwargs)


def test_binance_connect_factory(monkeypatch):
    sentinel = object()

    async def fake_connect(url, ping_interval=None, ping_timeout=None):
        assert "btcusdt@kline_4h" in url
        return sentinel

    fake_websockets = mock.MagicMock()
    fake_websockets.connect = fake_connect
    monkeypatch.setitem(sys.modules, "websockets", fake_websockets)

    connect = binance_connect_factory(["BTCUSDT", "ETHUSDT"], "4h")
    assert asyncio.run(connect()) is sentinel


def test_consumer_staleness_and_process(monkeypatch):
    upserted = []
    monkeypatch.setattr(
        kline_stream_mod, "upsert_klines", lambda engine, rows: upserted.append(rows)
    )
    now = pd.Timestamp("2026-07-01 04:00:00", tz="UTC")
    consumer = _consumer(now_fn=lambda: now)

    # No event yet: stale, no last event time.
    assert consumer.last_event_time("BTCUSDT") is None
    assert consumer.is_stale("BTCUSDT") is True

    # Closed candle: persisted, freshness tracked.
    consumer._process(_kline_message(closed=True))
    assert len(upserted) == 1
    assert consumer.last_event_time("BTCUSDT") is not None
    assert consumer.is_stale("BTCUSDT") is False

    # In-progress candle: freshness only, never persisted.
    consumer._process(_kline_message(closed=False))
    assert len(upserted) == 1

    # Malformed message is skipped, not raised.
    consumer._process("{not json")
    assert len(upserted) == 1

    # Two intervals later the pair is stale again.
    consumer._now = lambda: now + pd.Timedelta(hours=9)
    assert consumer.is_stale("BTCUSDT") is True


def test_heartbeat_none_and_failure():
    consumer = _consumer(heartbeat_fn=None)
    consumer._maybe_heartbeat()  # no-op without a heartbeat_fn

    def boom():
        raise RuntimeError("monitoring down")

    consumer = _consumer(heartbeat_fn=boom)
    consumer._maybe_heartbeat()  # failure is logged, never raised
    assert consumer._last_heartbeat is None


class _FakeConnection:
    def __init__(self, messages, tail_exc=None):
        self._messages = list(messages)
        self._tail_exc = tail_exc

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        if self._tail_exc is not None:
            raise self._tail_exc
        raise StopAsyncIteration


def test_run_processes_reconnects_and_stops(monkeypatch):
    monkeypatch.setattr(kline_stream_mod, "upsert_klines",
                        lambda engine, rows: None)
    connections = []

    async def connect():
        connections.append(1)
        if len(connections) == 1:
            # First connection drops with an error -> reconnect after sleep.
            return _FakeConnection([_kline_message()], RuntimeError("dropped"))
        return _FakeConnection([_kline_message()])

    consumer = _consumer(connect=connect, reconnect_delay=0.001,
                         heartbeat_fn=lambda: None, heartbeat_interval=0.0)
    asyncio.run(consumer.run(max_connections=2))
    assert len(connections) == 2


def test_run_propagates_cancellation():
    async def connect():
        return _FakeConnection([], asyncio.CancelledError())

    consumer = _consumer(connect=connect, reconnect_delay=0)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(consumer.run(max_connections=1))


# ---------------------------------------------------------------------------
# signal_service.py — remaining lines
# ---------------------------------------------------------------------------

import app.services.signal_service as signal_mod
from app.services.signal_service import (
    BinanceRestCandleSource,
    InsufficientDataError,
    generate_signal,
    get_candle_source,
    get_predictor,
    normalize_pair,
)


def _candles(n):
    start = pd.Timestamp("2026-01-01", tz="UTC")
    idx = np.arange(n)
    close = 100.0 + idx * 0.5 + np.sin(idx) * 2.0
    return pd.DataFrame(
        {
            "open_time": [start + int(i) * pd.Timedelta(hours=4) for i in idx],
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 10.0 + idx + np.cos(idx),
        }
    )


def test_binance_rest_candle_source(monkeypatch):
    import httpx

    now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    hour = 3600 * 1000
    rows = [
        # closed candles
        [now_ms - 9 * hour, "100", "101", "99", "100.5", "10", now_ms - 5 * hour],
        [now_ms - 5 * hour, "100.5", "102", "100", "101", "11", now_ms - hour],
        # still-open candle (close_time in the future) -> dropped
        [now_ms - hour, "101", "103", "100", "102", "12", now_ms + 3 * hour],
    ]
    response = mock.MagicMock()
    response.json.return_value = rows
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: response)

    frame = BinanceRestCandleSource().get_recent_candles("BTCUSDT", "4h", 3)
    assert len(frame) == 2
    assert "close_time" not in frame.columns
    assert frame["close"].tolist() == [100.5, 101.0]
    response.raise_for_status.assert_called_once()


def test_get_candle_source_default():
    from app.services.signal_service import FallbackCandleSource

    source = get_candle_source()
    # With a database available the default is Binance wrapped in a DB
    # fallback; without one it degrades to plain Binance.
    if isinstance(source, FallbackCandleSource):
        assert isinstance(source._primary, BinanceRestCandleSource)
    else:
        assert isinstance(source, BinanceRestCandleSource)


def test_normalize_pair():
    assert normalize_pair("btc-usdt") == "BTCUSDT"
    assert normalize_pair("ETH/usdt") == "ETHUSDT"
    assert normalize_pair("BTC$USDT") is None  # non-alnum after cleaning
    assert normalize_pair("DOGEUSDT") is None  # outside the universe


def test_generate_signal_insufficient_history():
    with pytest.raises(InsufficientDataError):
        generate_signal("BTCUSDT", _candles(10))


def test_generate_signal_baseline():
    signal = generate_signal("BTCUSDT", _candles(80))
    assert signal.pair == "BTC/USDT"
    assert signal.direction in ("long", "flat")
    assert 0.0 <= signal.confidence <= 1.0
    assert signal.model_version == signal_mod.MODEL_VERSION
    assert set(signal.model_votes) == {"ema_trend", "price_above_ema_50"}
    assert signal.stale is True  # candles end in January 2026


class _FakePredictor:
    version_id = "ens-v1"
    feature_columns = ["log_return_1", "rsi_14"]

    def prob_long(self, row):
        return 0.7

    def member_votes(self, row):
        return {"xgboost": "long", "lightgbm": "flat"}


def test_generate_signal_ensemble_path():
    signal = generate_signal("ETHUSDT", _candles(80), predictor=_FakePredictor())
    assert signal.pair == "ETH/USDT"
    assert signal.direction == "long"
    assert signal.confidence == pytest.approx(0.7)
    assert signal.model_version == "ens-v1"
    assert signal.model_votes == {"xgboost": "long", "lightgbm": "flat"}
    assert len(signal.top_features) == 2


def test_get_predictor_empty_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(signal_mod, "_PREDICTOR_CACHE", "unset")
    monkeypatch.setenv("MODEL_REGISTRY_PATH", str(tmp_path))
    assert get_predictor() is None
    assert get_predictor() is None  # memoized


def test_get_predictor_swallows_load_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(signal_mod, "_PREDICTOR_CACHE", "unset")
    (tmp_path / "registry.json").write_text("{not valid json")
    monkeypatch.setenv("MODEL_REGISTRY_PATH", str(tmp_path))
    assert get_predictor() is None
