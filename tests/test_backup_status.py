"""
Backup freshness as a health component. The nightly backup + restore drill
fail loudly, but only into a host log file; surfacing freshness in
/health/detailed puts a broken backup pipeline on the dashboard's System
Health card instead.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.backup_status import backup_status

NOW = datetime(2026, 8, 5, 12, 0, 0)


def _touch(tmp_path, stamp):
    (tmp_path / f"aif-db-{stamp}.sql.gz").write_bytes(b"x")


def test_fresh_backup_is_healthy(tmp_path):
    _touch(tmp_path, "20260805-031700")  # ~9h old
    status = backup_status(str(tmp_path), now=NOW)
    assert status["status"] == "healthy"
    assert status["latest_backup"] == "aif-db-20260805-031700.sql.gz"
    assert 8 < status["age_hours"] < 10


def test_old_backup_is_stale(tmp_path):
    _touch(tmp_path, "20260802-031700")  # 3+ days old
    status = backup_status(str(tmp_path), now=NOW)
    assert status["status"] == "stale"


def test_newest_backup_wins(tmp_path):
    _touch(tmp_path, "20260801-031700")
    _touch(tmp_path, "20260805-031700")
    status = backup_status(str(tmp_path), now=NOW)
    assert status["status"] == "healthy"


def test_no_backups_is_missing(tmp_path):
    (tmp_path / "unrelated.txt").write_text("not a backup")
    status = backup_status(str(tmp_path), now=NOW)
    assert status["status"] == "missing"
    assert status["latest_backup"] is None


def test_unset_directory_is_not_configured():
    status = backup_status(None, now=NOW)
    assert status["status"] == "not_configured"


def test_nonexistent_directory_is_missing():
    status = backup_status("/does/not/exist", now=NOW)
    assert status["status"] == "missing"


def test_detailed_health_includes_backup_component(tmp_path, monkeypatch):
    _touch(tmp_path, "20260805-031700")
    monkeypatch.setenv("BACKUP_STATUS_DIR", str(tmp_path))
    client = TestClient(app)
    body = client.get("/api/v1/health/detailed").json()
    assert "backups" in body["components"]
    assert body["components"]["backups"]["status"] in ("healthy", "stale", "missing")


def test_detailed_health_database_probe_uses_executable_statement():
    """Regression: the probe passed a raw string to session.execute, which
    SQLAlchemy 2.x rejects — production showed 'database unhealthy' while
    the database was fine."""
    from unittest.mock import AsyncMock, MagicMock

    from app.core.database import get_db

    class Sqla2Session:
        async def execute(self, stmt):
            if isinstance(stmt, str):
                raise Exception("Textual SQL expression should be explicit")
            result = MagicMock()
            result.fetchone = AsyncMock(return_value=(1,))
            return result

    async def _get_db():
        yield Sqla2Session()

    app.dependency_overrides[get_db] = _get_db
    try:
        body = TestClient(app).get("/api/v1/health/detailed").json()
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert body["components"]["database"]["status"] == "healthy"
