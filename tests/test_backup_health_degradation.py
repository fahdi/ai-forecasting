"""
Whether a stale backup actually degrades /health/detailed.

app/services/backup_status.py decides the component's own status, and that is
well covered. What was not covered is the line in health.py that turns a bad
backup into an overall "degraded" - the only reason anyone would notice. It
was the last uncovered statement in the health path.

The coupling was two hand-written string literals in different modules:
backup_status.py emits "stale"/"missing"/"healthy"/"not_configured", and
health.py separately checked `in ("stale", "missing")`. Rename one and
backups rot silently while the endpoint reports healthy - the same failure
that hid the market-data outage for five days.

The producer now owns which of its statuses are faults, and these tests pin
the end-to-end behaviour plus the classification of every status it can emit.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.services.backup_status import (
    BENIGN_STATUSES,
    DEGRADED_STATUSES,
    PREFIX,
    STAMP_FORMAT,
    backup_status,
)

client = TestClient(app)


def _write_backup(directory, age_hours: float):
    stamp = (datetime.utcnow() - timedelta(hours=age_hours)).strftime(STAMP_FORMAT)
    path = directory / f"{PREFIX}{stamp}.sql.gz"
    path.write_bytes(b"-- PostgreSQL database dump\n")
    return path


@pytest.fixture
def healthy_stack(tmp_path, monkeypatch):
    """Everything except backups healthy, so `degraded` can only come from them."""
    result = MagicMock()
    result.fetchone = AsyncMock(return_value=(1,))
    result.scalar = MagicMock(
        return_value=int(datetime.utcnow().timestamp() * 1000)
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    async def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db

    for name in ("DATA_STORAGE_PATH", "MODEL_STORAGE_PATH"):
        directory = tmp_path / name.lower()
        directory.mkdir()
        monkeypatch.setattr(settings, name, str(directory))

    redis_mod = MagicMock()
    redis_client = MagicMock()
    redis_client.ping = AsyncMock(return_value=True)
    redis_client.close = AsyncMock()
    redis_mod.from_url.return_value = redis_client

    def _get(backup_dir=None):
        if backup_dir is None:
            monkeypatch.delenv("BACKUP_STATUS_DIR", raising=False)
        else:
            monkeypatch.setenv("BACKUP_STATUS_DIR", str(backup_dir))
        with patch("app.api.v1.endpoints.health.redis", redis_mod):
            return client.get("/api/v1/health/detailed").json()

    yield _get
    app.dependency_overrides.pop(get_db, None)


class TestEndToEnd:
    def test_fresh_backup_leaves_the_stack_healthy(self, healthy_stack, tmp_path):
        backups = tmp_path / "backups"
        backups.mkdir()
        _write_backup(backups, age_hours=2)

        body = healthy_stack(backups)
        assert body["components"]["backups"]["status"] == "healthy"
        assert body["status"] == "healthy"

    def test_stale_backup_degrades_the_endpoint(self, healthy_stack, tmp_path):
        """A backup pipeline that quietly stopped days ago."""
        backups = tmp_path / "backups"
        backups.mkdir()
        _write_backup(backups, age_hours=72)

        body = healthy_stack(backups)
        assert body["components"]["backups"]["status"] == "stale"
        assert body["status"] == "degraded"

    def test_no_backups_at_all_degrades_the_endpoint(self, healthy_stack, tmp_path):
        backups = tmp_path / "backups"
        backups.mkdir()

        body = healthy_stack(backups)
        assert body["components"]["backups"]["status"] == "missing"
        assert body["status"] == "degraded"

    def test_unconfigured_backups_do_not_degrade(self, healthy_stack):
        """Local dev has no backup dir; that is not an incident."""
        body = healthy_stack(None)
        assert body["components"]["backups"]["status"] == "not_configured"
        assert body["status"] == "healthy"


class TestStatusClassification:
    """Guards the producer/consumer coupling that used to be two literals."""

    def test_degraded_and_benign_do_not_overlap(self):
        assert not (DEGRADED_STATUSES & BENIGN_STATUSES)

    def test_every_status_the_producer_can_emit_is_classified(self, tmp_path):
        """Add a new status without deciding whether it is a fault and fail."""
        empty = tmp_path / "empty"
        empty.mkdir()
        fresh = tmp_path / "fresh"
        fresh.mkdir()
        _write_backup(fresh, age_hours=1)
        old = tmp_path / "old"
        old.mkdir()
        _write_backup(old, age_hours=500)

        emitted = {
            backup_status(None)["status"],
            backup_status(str(empty))["status"],
            backup_status(str(fresh))["status"],
            backup_status(str(old))["status"],
        }

        unclassified = emitted - DEGRADED_STATUSES - BENIGN_STATUSES
        assert not unclassified, (
            f"backup_status can emit {sorted(unclassified)}, which health.py "
            "neither degrades on nor treats as benign"
        )

    def test_stale_and_missing_are_the_faults(self):
        assert DEGRADED_STATUSES == {"stale", "missing"}
