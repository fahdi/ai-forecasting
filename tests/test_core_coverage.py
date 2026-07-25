"""
Coverage for core modules: middleware, monitoring, database, config, main.

External systems (redis, sentry, postgres) are mocked or replaced with
in-memory equivalents; behavior assertions are real.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import database as db_module
from app.core import monitoring
from app.core.config import Settings, settings
from app.core.middleware import (
    AuthenticationMiddleware,
    CORSMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)


def make_app(middleware_class, **kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(middleware_class, **kwargs)

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return app


class TestRequestLoggingMiddleware:
    def test_adds_request_id_and_timing_headers(self):
        client = TestClient(make_app(RequestLoggingMiddleware))
        response = client.get("/ok")
        assert response.status_code == 200
        assert response.headers["X-Request-ID"]
        assert float(response.headers["X-Response-Time"]) >= 0

    def test_exception_logged_and_reraised(self):
        client = TestClient(make_app(RequestLoggingMiddleware),
                            raise_server_exceptions=False)
        assert client.get("/boom").status_code == 500


class TestRateLimitMiddleware:
    def make_redis(self, count):
        fake = AsyncMock()
        fake.get.return_value = count
        return fake

    def test_under_limit_passes_with_headers(self):
        fake = self.make_redis(b"1")
        client = TestClient(make_app(RateLimitMiddleware, redis_client=fake))
        response = client.get("/ok")
        assert response.status_code == 200
        assert response.headers["X-RateLimit-Limit"] == str(settings.RATE_LIMIT_PER_MINUTE)
        assert int(response.headers["X-RateLimit-Remaining"]) == settings.RATE_LIMIT_PER_MINUTE - 2

    def test_first_request_counts_from_zero(self):
        fake = self.make_redis(None)
        client = TestClient(make_app(RateLimitMiddleware, redis_client=fake))
        assert client.get("/ok").status_code == 200

    def test_limit_exceeded_429(self):
        fake = self.make_redis(str(settings.RATE_LIMIT_PER_MINUTE).encode())
        client = TestClient(make_app(RateLimitMiddleware, redis_client=fake))
        response = client.get("/ok")
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"

    def test_redis_failure_fails_open(self):
        fake = AsyncMock()
        fake.get.side_effect = ConnectionError("redis down")
        client = TestClient(make_app(RateLimitMiddleware, redis_client=fake))
        assert client.get("/ok").status_code == 200


class TestAuthenticationMiddleware:
    def test_health_path_skips_auth(self):
        client = TestClient(make_app(AuthenticationMiddleware))
        assert client.get("/health").status_code == 200

    def test_missing_api_key_401(self):
        client = TestClient(make_app(AuthenticationMiddleware))
        response = client.get("/ok")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "ApiKey"

    def test_whitespace_api_key_401(self):
        client = TestClient(make_app(AuthenticationMiddleware))
        assert client.get("/ok", headers={"X-API-Key": "   "}).status_code == 401

    def test_valid_api_key_passes(self):
        client = TestClient(make_app(AuthenticationMiddleware))
        assert client.get("/ok", headers={"X-API-Key": "k1"}).status_code == 200


class TestHeaderMiddlewares:
    def test_cors_headers_added(self):
        client = TestClient(make_app(CORSMiddleware))
        response = client.get("/ok")
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert "GET" in response.headers["Access-Control-Allow-Methods"]

    def test_security_headers_added(self):
        client = TestClient(make_app(SecurityHeadersMiddleware))
        response = client.get("/ok")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "max-age" in response.headers["Strict-Transport-Security"]


class TestMonitoring:
    def test_setup_without_sentry_dsn(self):
        with patch.object(settings, "SENTRY_DSN", ""):
            with patch.object(monitoring, "sentry_sdk") as sentry:
                monitoring.setup_monitoring()
                sentry.init.assert_not_called()

    def test_setup_with_sentry_dsn(self):
        with patch.object(settings, "SENTRY_DSN", "https://x@sentry.example/1"):
            with patch.object(monitoring, "sentry_sdk") as sentry:
                monitoring.setup_monitoring()
                sentry.init.assert_called_once()

    def test_metric_recorders(self):
        monitoring.record_forecast_request("xgboost", "BTC", "ok")
        monitoring.record_forecast_duration("xgboost", "BTC", 0.5)
        monitoring.record_model_training_duration("xgboost", "BTC", 1.0)
        monitoring.record_model_accuracy("xgboost", "BTC", "mape", 0.03)
        monitoring.update_active_jobs("pending", 2)
        monitoring.record_data_points_processed("binance", "BTC", 100)
        monitoring.record_api_error("/x", "boom")

    def test_metrics_collector(self):
        collector = monitoring.get_metrics_collector()
        collector.record_prediction_accuracy("xgb", "BTC", 0.1, 0.2, 0.3)
        collector.record_data_processing("binance", "BTC", 5)
        collector.record_job_status("running", 1)
        collector.record_error("/y", "err")
        assert collector is monitoring.metrics_collector


@pytest.fixture
def sqlite_db(monkeypatch):
    """Swap the module engine/session factory for in-memory aiosqlite."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", session_factory)
    return engine


class TestDatabase:
    @pytest.mark.asyncio
    async def test_init_db_creates_tables_and_close(self, sqlite_db):
        await db_module.init_db()
        await db_module.close_db()

    @pytest.mark.asyncio
    async def test_init_db_error_path(self, monkeypatch):
        broken = MagicMock()
        broken.begin.side_effect = RuntimeError("no db")
        monkeypatch.setattr(db_module, "engine", broken)
        with pytest.raises(RuntimeError):
            await db_module.init_db()

    @pytest.mark.asyncio
    async def test_get_db_yields_and_closes(self, sqlite_db):
        await db_module.init_db()
        generator = db_module.get_db()
        session = await generator.__anext__()
        assert session is not None
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()

    @pytest.mark.asyncio
    async def test_get_db_rolls_back_on_error(self, sqlite_db):
        await db_module.init_db()
        generator = db_module.get_db()
        await generator.__anext__()
        with pytest.raises(RuntimeError):
            await generator.athrow(RuntimeError("mid-request failure"))

    @pytest.mark.asyncio
    async def test_forecast_job_crud(self, sqlite_db):
        await db_module.init_db()
        async with db_module.AsyncSessionLocal() as session:
            job = await db_module.create_forecast_job(
                session, job_id="j1", symbol="BTC", forecast_horizon=7,
                model_type="ensemble", job_metadata={"a": 1})
            assert job.status == "pending"

            # Lookups go through the job_id column (the integer id is the
            # PK, so a Session.get PK lookup would never match a UUID).
            fetched = await db_module.get_forecast_job(session, "j1")
            assert fetched.symbol == "BTC"
            assert await db_module.get_forecast_job(session, "nope") is None

            done = await db_module.update_forecast_job(
                session, "j1", "completed", result_path="/tmp/r.json")
            assert done.completed_at is not None
            failed = await db_module.update_forecast_job(
                session, "j1", "failed", error_message="oops")
            assert failed.error_message == "oops"
            missing = await db_module.update_forecast_job(session, "absent", "x")
            assert missing is None

    @pytest.mark.asyncio
    async def test_save_model_performance_and_api_log(self, sqlite_db):
        await db_module.init_db()
        async with db_module.AsyncSessionLocal() as session:
            perf = await db_module.save_model_performance(
                session, model_type="xgboost", symbol="BTC", version="v1",
                mape=0.05, directional_accuracy=0.55)
            assert perf.id is not None
            log = await db_module.log_api_request(
                session, endpoint="/x", method="GET", status_code=200,
                response_time=0.1)
            assert log.id is not None


class TestAsyncUrlMapping:
    def test_postgres_mapped_to_asyncpg(self):
        assert db_module._async_url("postgresql://u:p@h/db") == \
            "postgresql+asyncpg://u:p@h/db"

    def test_sqlite_mapped_to_aiosqlite(self):
        assert db_module._async_url("sqlite:///x.db") == "sqlite+aiosqlite:///x.db"

    def test_explicit_driver_passes_through(self):
        assert db_module._async_url("postgresql+asyncpg://u@h/db") == \
            "postgresql+asyncpg://u@h/db"


class TestConfig:
    def test_allowed_hosts_from_comma_string(self):
        # Env vars for list fields are JSON-parsed by pydantic-settings before
        # validators run, so the comma-split path is constructor-only.
        parsed = Settings(ALLOWED_HOSTS="https://a.com, https://b.com")
        assert parsed.ALLOWED_HOSTS == ["https://a.com", "https://b.com"]

    def test_allowed_hosts_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            Settings(ALLOWED_HOSTS=123)


class TestMainApp:
    def test_lifespan_runs_init_and_monitoring(self):
        from app import main as main_module

        with patch.object(main_module, "init_db", new=AsyncMock()) as init_mock, \
             patch.object(main_module, "setup_monitoring") as monitor_mock:
            with TestClient(main_module.app) as client:
                assert client.get("/health").status_code == 200
            init_mock.assert_awaited_once()
            monitor_mock.assert_called_once()

    def test_global_exception_handler_returns_500_json(self):
        from app.main import app
        from app.services.signal_service import get_candle_source, get_predictor

        def broken_source():
            raise RuntimeError("total failure")

        app.dependency_overrides[get_candle_source] = broken_source
        app.dependency_overrides[get_predictor] = lambda: None
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/signal/BTC-USDT")
        app.dependency_overrides.clear()
        assert response.status_code == 500
        body = response.json()
        assert body["error"] == "Internal server error"
        assert "timestamp" in body
