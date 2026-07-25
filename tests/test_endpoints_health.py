"""
Coverage tests for app/api/v1/endpoints/health.py

TestClient is used WITHOUT a context manager so the DB lifespan never runs;
the async get_db dependency is overridden with a mock session so no live
Postgres/Redis is required.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.core.config import settings

client = TestClient(app)


def make_db_session(healthy: bool = True) -> MagicMock:
    session = MagicMock()
    if healthy:
        result = MagicMock()
        result.fetchone = AsyncMock(return_value=(1,))
        session.execute = AsyncMock(return_value=result)
    else:
        session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    return session


def make_redis_module(healthy: bool = True) -> MagicMock:
    redis_mod = MagicMock()
    redis_client = MagicMock()
    if healthy:
        redis_client.ping = AsyncMock(return_value=True)
    else:
        redis_client.ping = AsyncMock(side_effect=ConnectionError("no redis"))
    redis_client.close = AsyncMock()
    redis_mod.from_url.return_value = redis_client
    return redis_mod


@pytest.fixture
def db_override():
    """Install a mock async session behind get_db; uninstall afterwards."""

    def _install(session):
        async def _get_db():
            yield session

        app.dependency_overrides[get_db] = _get_db
        return session

    yield _install
    app.dependency_overrides.pop(get_db, None)


class TestBasicProbes:
    def test_health_root(self):
        response = client.get("/api/v1/health/")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["service"] == "ai-forecasting-api"
        assert "timestamp" in body and "version" in body

    def test_readiness(self):
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert "timestamp" in body

    def test_liveness(self):
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "alive"
        assert "timestamp" in body


class TestDetailedHealth:
    def test_all_components_healthy(self, db_override, monkeypatch, tmp_path):
        db_override(make_db_session(healthy=True))
        data_dir = tmp_path / "data"
        model_dir = tmp_path / "models"
        data_dir.mkdir()
        model_dir.mkdir()
        monkeypatch.setattr(settings, "DATA_STORAGE_PATH", str(data_dir))
        monkeypatch.setattr(settings, "MODEL_STORAGE_PATH", str(model_dir))

        with patch("app.api.v1.endpoints.health.redis", make_redis_module(True)):
            response = client.get("/api/v1/health/detailed")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        components = body["components"]
        for name in ("database", "redis", "storage", "model_storage", "ml_libraries"):
            assert components[name]["status"] == "healthy", name
        # ML library versions are reported when all imports succeed
        versions = components["ml_libraries"]["versions"]
        assert {"pandas", "numpy", "xgboost", "lightgbm", "catboost"} <= set(versions)

    def test_all_components_degraded(self, db_override, monkeypatch, tmp_path):
        """DB error, Redis error, missing storage paths, broken ML import."""
        db_override(make_db_session(healthy=False))
        monkeypatch.setattr(settings, "DATA_STORAGE_PATH", str(tmp_path / "missing-data"))
        monkeypatch.setattr(settings, "MODEL_STORAGE_PATH", str(tmp_path / "missing-models"))

        # None in sys.modules makes `import xgboost` raise ImportError,
        # driving the ml_libraries except-branch without uninstalling anything.
        with patch("app.api.v1.endpoints.health.redis", make_redis_module(False)), \
             patch.dict(sys.modules, {"xgboost": None}):
            response = client.get("/api/v1/health/detailed")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        components = body["components"]
        assert components["database"]["status"] == "unhealthy"
        assert "db down" in components["database"]["message"]
        assert components["redis"]["status"] == "unhealthy"
        assert components["storage"]["status"] == "unhealthy"
        assert components["storage"]["message"] == "Storage path not accessible"
        assert components["model_storage"]["status"] == "unhealthy"
        assert components["ml_libraries"]["status"] == "unhealthy"

    def test_storage_checks_raising_are_reported(self, db_override, monkeypatch, tmp_path):
        """os.access blowing up hits the storage/model-storage except branches."""
        db_override(make_db_session(healthy=True))
        data_dir = tmp_path / "data"
        model_dir = tmp_path / "models"
        data_dir.mkdir()
        model_dir.mkdir()
        monkeypatch.setattr(settings, "DATA_STORAGE_PATH", str(data_dir))
        monkeypatch.setattr(settings, "MODEL_STORAGE_PATH", str(model_dir))

        with patch("app.api.v1.endpoints.health.redis", make_redis_module(True)), \
             patch("os.access", side_effect=RuntimeError("perm probe failed")):
            response = client.get("/api/v1/health/detailed")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        components = body["components"]
        assert components["storage"]["status"] == "unhealthy"
        assert "Storage check failed" in components["storage"]["message"]
        assert components["model_storage"]["status"] == "unhealthy"
        assert "Model storage check failed" in components["model_storage"]["message"]
