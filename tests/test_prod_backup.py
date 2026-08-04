"""
Production DB backup script (scripts/prod_backup.py).

The VPS Postgres holds the forecast history and the prediction audit trail
(PRD R13/R17); it has no host port, so backups go through `docker compose
exec pg_dump`. The dump command itself is injected — these tests cover the
parts that can silently rot: naming, integrity verification, retention.
"""

import gzip
import sys
from datetime import datetime
from pathlib import Path

import pytest

from scripts.prod_backup import (
    PREFIX,
    backup_filename,
    prune_old_backups,
    run_backup,
    verify_gzip_sql,
)


NOW = datetime(2026, 8, 5, 3, 17, 0)


def _write_backup(directory: Path, stamp: str, content: bytes = b"-- PostgreSQL database dump\n") -> Path:
    path = directory / f"{PREFIX}{stamp}.sql.gz"
    with gzip.open(path, "wb") as fh:
        fh.write(content)
    return path


def test_backup_filename_is_sortable_and_parseable():
    name = backup_filename(NOW)
    assert name == f"{PREFIX}20260805-031700.sql.gz"


def test_prune_removes_only_old_matching_files(tmp_path):
    old = _write_backup(tmp_path, "20260720-031700")      # 16 days old
    recent = _write_backup(tmp_path, "20260804-031700")   # 1 day old
    unrelated = tmp_path / "keep-me.sql.gz"
    unrelated.write_bytes(b"not a backup")
    malformed = tmp_path / f"{PREFIX}not-a-date.sql.gz"
    malformed.write_bytes(b"x")

    removed = prune_old_backups(tmp_path, keep_days=14, now=NOW)

    assert removed == [old.name]
    assert not old.exists()
    assert recent.exists()
    assert unrelated.exists()
    assert malformed.exists()


def test_verify_accepts_real_dump_and_rejects_garbage(tmp_path):
    good = _write_backup(tmp_path, "20260805-031700")
    assert verify_gzip_sql(good) is True

    empty = tmp_path / f"{PREFIX}20260805-031701.sql.gz"
    with gzip.open(empty, "wb") as fh:
        fh.write(b"")
    assert verify_gzip_sql(empty) is False

    truncated = tmp_path / f"{PREFIX}20260805-031702.sql.gz"
    truncated.write_bytes(b"\x1f\x8b\x08\x00garbage")
    assert verify_gzip_sql(truncated) is False

    not_sql = tmp_path / f"{PREFIX}20260805-031703.sql.gz"
    with gzip.open(not_sql, "wb") as fh:
        fh.write(b"<html>error page</html>")
    assert verify_gzip_sql(not_sql) is False


def test_run_backup_writes_verified_dump_and_prunes(tmp_path):
    _write_backup(tmp_path, "20260701-031700")  # should be pruned

    path = run_backup(
        backup_dir=tmp_path,
        keep_days=14,
        dump_cmd=[sys.executable, "-c", "print('-- PostgreSQL database dump'); print('SELECT 1;')"],
        now=NOW,
    )

    assert path.exists() and path.name == backup_filename(NOW)
    with gzip.open(path, "rb") as fh:
        assert b"PostgreSQL database dump" in fh.read()
    assert not (tmp_path / f"{PREFIX}20260701-031700.sql.gz").exists()


def test_run_backup_fails_loudly_on_empty_dump(tmp_path):
    with pytest.raises(RuntimeError):
        run_backup(
            backup_dir=tmp_path,
            keep_days=14,
            dump_cmd=["true"],  # produces no output
            now=NOW,
        )
    # A failed dump must not leave a bogus backup file behind
    assert list(tmp_path.glob(f"{PREFIX}*.sql.gz")) == []


def test_run_backup_fails_loudly_when_dump_command_errors(tmp_path):
    with pytest.raises(RuntimeError):
        run_backup(
            backup_dir=tmp_path,
            keep_days=14,
            dump_cmd=["false"],
            now=NOW,
        )
    assert list(tmp_path.glob(f"{PREFIX}*.sql.gz")) == []
