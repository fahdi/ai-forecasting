"""
Coverage for trading-path remainders: real-source adapters (HTTP mocked),
predictor loading branches, registry validation, endpoint edge branches.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app.services.signal_service as signal_service_module
from app.main import app
from app.api.v1.endpoints.chart import get_chart_engine
from app.models.registry import ModelRegistry
from app.services.kline_backfill import (
    KlineValidationError,
    TransientFetchError,
    fetch_binance_page,
    parse_binance_klines,
)
from app.services.kline_store import upsert_klines
from app.services.kline_stream import KlineStreamConsumer, binance_connect_factory
from app.services.signal_service import (
    BinanceRestCandleSource,
    get_candle_source,
    get_predictor,
    normalize_pair,
)


class FakeHttpResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("boom", request=MagicMock(),
                                        response=MagicMock())


def raw_kline_row(open_time_ms, close_time_ms):
    return [open_time_ms, "100", "101", "99", "100", "5.0", close_time_ms]


class TestBinanceRestCandleSource:
    def test_fetch_parses_and_drops_open_candle(self):
        now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
        payload = [
            raw_kline_row(now_ms - 8 * 3_600_000, now_ms - 4 * 3_600_000),
            raw_kline_row(now_ms - 4 * 3_600_000, now_ms + 4 * 3_600_000),  # open
        ]
        with patch("httpx.get", return_value=FakeHttpResponse(payload)) as http_get:
            frame = BinanceRestCandleSource().get_recent_candles("BTCUSDT", "4h", 10)
        assert len(frame) == 1  # the still-open candle was dropped
        assert list(frame.columns) == ["open_time", "open", "high", "low",
                                       "close", "volume"]
        assert http_get.call_args.kwargs["params"]["symbol"] == "BTCUSDT"

    def test_default_candle_source_is_binance_first(self):
        from app.services.signal_service import FallbackCandleSource

        source = get_candle_source()
        if isinstance(source, FallbackCandleSource):
            assert isinstance(source._primary, BinanceRestCandleSource)
        else:
            assert isinstance(source, BinanceRestCandleSource)


class TestFetchBinancePage:
    def test_success(self):
        payload = [raw_kline_row(0, 100)]
        with patch("httpx.get", return_value=FakeHttpResponse(payload)):
            assert fetch_binance_page("BTCUSDT", "4h", 0, 10) == payload

    def test_rate_limit_is_transient(self):
        with patch("httpx.get", return_value=FakeHttpResponse([], status_code=429)):
            with pytest.raises(TransientFetchError, match="429"):
                fetch_binance_page("BTCUSDT", "4h", 0, 10)

    def test_server_error_is_transient(self):
        with patch("httpx.get", return_value=FakeHttpResponse([], status_code=503)):
            with pytest.raises(TransientFetchError):
                fetch_binance_page("BTCUSDT", "4h", 0, 10)

    def test_transport_error_is_transient(self):
        import httpx

        with patch("httpx.get", side_effect=httpx.ConnectError("down")):
            with pytest.raises(TransientFetchError):
                fetch_binance_page("BTCUSDT", "4h", 0, 10)

    def test_client_error_raises_permanent(self):
        import httpx

        with patch("httpx.get", return_value=FakeHttpResponse([], status_code=404)):
            with pytest.raises(httpx.HTTPStatusError):
                fetch_binance_page("BTCUSDT", "4h", 0, 10)

    def test_negative_volume_rejected(self):
        bad = raw_kline_row(0, 100)
        bad[5] = "-1"
        with pytest.raises(KlineValidationError, match="volume"):
            parse_binance_klines("BTCUSDT", "4h", [bad])


class TestBackfillEndBound:
    def test_stops_at_end_ms(self):
        from sqlalchemy import create_engine

        from app.services.kline_backfill import backfill
        from app.services.kline_store import create_tables

        engine = create_engine("sqlite://")
        create_tables(engine)
        four_h = 4 * 3_600_000

        def fetch(symbol, interval, start_ms, limit):
            return [raw_kline_row(start_ms + i * four_h,
                                  start_ms + (i + 1) * four_h - 1)[:6] + [0]
                    for i in range(10)]

        stored = backfill(fetch, engine, "BTCUSDT", "4h", start_ms=0,
                          end_ms=5 * four_h)
        assert stored == 10  # one page fetched, then the end bound stops it


class TestKlineStorePostgresBranch:
    def test_postgres_dialect_selected(self):
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        connection = MagicMock()
        engine.begin.return_value.__enter__ = MagicMock(return_value=connection)
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        rows = [{"pair": "BTCUSDT", "interval": "4h", "open_time_ms": 0,
                 "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                 "volume": 1.0}]
        upsert_klines(engine, rows)
        statement = connection.execute.call_args.args[0]
        assert "ON CONFLICT" in str(
            statement.compile(dialect=__import__(
                "sqlalchemy.dialects.postgresql", fromlist=["dialect"]
            ).dialect())
        )

    def test_empty_rows_no_op(self):
        engine = MagicMock()
        upsert_klines(engine, [])
        engine.begin.assert_not_called()


class TestKlineStreamRemainders:
    def test_connect_factory_builds_combined_stream_url(self, monkeypatch):
        import websockets

        captured = {}

        async def fake_connect(url, **kwargs):
            captured["url"] = url
            return "sentinel"

        monkeypatch.setattr(websockets, "connect", fake_connect)
        connect = binance_connect_factory(["BTCUSDT", "ETHUSDT"], "4h")
        result = asyncio.run(connect())
        assert result == "sentinel"
        assert "btcusdt@kline_4h/ethusdt@kline_4h" in captured["url"]

    @pytest.mark.asyncio
    async def test_cancellation_propagates(self):
        async def cancelled_connect():
            raise asyncio.CancelledError()

        consumer = KlineStreamConsumer(MagicMock(), ["BTCUSDT"], "4h",
                                       connect=cancelled_connect)
        with pytest.raises(asyncio.CancelledError):
            await consumer.run(max_connections=1)

    @pytest.mark.asyncio
    async def test_heartbeat_rate_limited(self):
        from sqlalchemy import create_engine

        from app.services.kline_store import create_tables
        from tests.test_kline_stream import kline_message, make_connect

        engine = create_engine("sqlite://")
        create_tables(engine)
        pings = []
        four_h = 4 * 3_600_000
        connect = make_connect(
            [[kline_message("BTCUSDT", 0, closed=True),
              kline_message("BTCUSDT", four_h, closed=True)]]
        )
        consumer = KlineStreamConsumer(
            engine, ["BTCUSDT"], "4h", connect=connect,
            heartbeat_fn=lambda: pings.append(1),
            heartbeat_interval=3600,  # second message inside the window
        )
        await consumer.run(max_connections=1)
        assert len(pings) == 1  # rate limit suppressed the second ping

    @pytest.mark.asyncio
    async def test_nonzero_reconnect_delay_sleeps(self):
        class EmptyConnection:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        async def connect():
            return EmptyConnection()

        consumer = KlineStreamConsumer(MagicMock(), ["BTCUSDT"], "4h",
                                       connect=connect, reconnect_delay=0.001)
        await consumer.run(max_connections=2)


class TestPredictorLoading:
    def test_load_active_missing_registry_returns_none(self, tmp_path):
        from app.models.ensemble_predictor import load_active

        assert load_active(tmp_path / "nope") is None

    def test_load_active_no_active_version_returns_none(self, tmp_path):
        from app.models.ensemble_predictor import load_active

        registry = ModelRegistry(tmp_path / "reg")
        # Registered but never promoted: index exists with active=None.
        registry.register("v1", {"directional_accuracy": 0.6}, ["rsi_14"],
                          {"start": "a", "end": "b"})
        assert load_active(tmp_path / "reg") is None

    def test_prob_long_series_matches_single_row_prob(self):
        import numpy as np

        from app.models.crypto_features import FEATURE_COLUMNS
        from app.models.ensemble_predictor import EnsemblePredictor
        from app.models.ensemble_trainer import TINY_PARAMS, build_dataset, fit_ensemble
        from tests.test_signal_endpoint import FakeCandleSource

        candles = FakeCandleSource(trend="up", noise=0.02).get_recent_candles(
            "BTCUSDT", "4h", 200)
        X, y, _ = build_dataset(candles)
        models = fit_ensemble(X, y, TINY_PARAMS, seed=7)
        predictor = EnsemblePredictor("t1", models, FEATURE_COLUMNS)

        series = predictor.prob_long_series(X.tail(5))
        assert len(series) == 5
        assert np.all((series >= 0) & (series <= 1))
        assert series[-1] == pytest.approx(predictor.prob_long(X.tail(1)))

    def test_load_active_no_artifacts_returns_none(self, tmp_path):
        from app.models.ensemble_predictor import load_active

        registry = ModelRegistry(tmp_path / "reg")
        registry.register("v1", {"directional_accuracy": 0.6}, ["rsi_14"],
                          {"start": "a", "end": "b"})
        registry.promote("v1")
        (registry.artifact_dir("v1") / "manifest.json").write_text(
            json.dumps({"feature_columns": ["rsi_14"]}))
        assert load_active(tmp_path / "reg") is None  # no .joblib files

    def test_registry_requires_primary_metric(self, tmp_path):
        registry = ModelRegistry(tmp_path / "reg")
        with pytest.raises(ValueError, match="directional_accuracy"):
            registry.register("v1", {"sharpe": 1.0}, [], {})


class TestGetPredictorCache:
    def test_loads_from_env_and_caches(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODEL_REGISTRY_PATH", str(tmp_path / "empty"))
        monkeypatch.setattr(signal_service_module, "_PREDICTOR_CACHE", "unset")
        assert get_predictor() is None          # empty path -> None
        assert get_predictor() is None          # cached path

    def test_loader_exception_caches_none(self, monkeypatch):
        monkeypatch.setattr(signal_service_module, "_PREDICTOR_CACHE", "unset")
        with patch("app.models.ensemble_predictor.load_active",
                   side_effect=RuntimeError("corrupt registry")):
            assert get_predictor() is None


class TestNormalizePair:
    def test_variants(self):
        assert normalize_pair("btc-usdt") == "BTCUSDT"
        assert normalize_pair("BTC/USDT") == "BTCUSDT"
        assert normalize_pair("eth_usdt") == "ETHUSDT"
        assert normalize_pair("DOGEUSDT") is None
        assert normalize_pair("not!!a@pair") is None


class TestEndpointEdgeBranches:
    @pytest.fixture
    def client(self):
        app.dependency_overrides[get_predictor] = lambda: None
        yield TestClient(app, raise_server_exceptions=True)
        app.dependency_overrides.clear()

    def test_chart_engine_none_gives_503_on_both_routes(self, client):
        app.dependency_overrides[get_chart_engine] = lambda: None
        assert client.get("/api/v1/chart/BTC-USDT/candles").status_code == 503
        assert client.get("/api/v1/chart/BTC-USDT/predictions").status_code == 503

    def test_chart_engine_passthrough_uses_health_engine(self):
        with patch("app.api.v1.endpoints.chart.get_health_engine",
                   return_value="the-engine"):
            assert get_chart_engine() == "the-engine"

    def test_training_window_end_none_when_registry_missing(self, tmp_path,
                                                            monkeypatch):
        from app.api.v1.endpoints.chart import _training_window_end

        monkeypatch.setenv("MODEL_REGISTRY_PATH", str(tmp_path / "missing"))
        assert _training_window_end() is None

    def test_signal_recording_failure_does_not_fail_request(self, client):
        from app.api.v1.endpoints.models import get_health_engine
        from tests.test_signal_endpoint import FakeCandleSource

        broken_engine = MagicMock()
        broken_engine.begin.side_effect = RuntimeError("db gone")
        app.dependency_overrides[get_candle_source] = lambda: FakeCandleSource()
        app.dependency_overrides[get_health_engine] = lambda: broken_engine
        response = client.get("/api/v1/signal/BTC-USDT")
        assert response.status_code == 200  # R6 logging must never break serving
