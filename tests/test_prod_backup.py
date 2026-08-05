"""
Production DB backup script (scripts/prod_backup.py).

The VPS Postgres holds the forecast history and the prediction audit trail
(PRD R13/R17); it has no host port, so backups go through `docker compose
exec pg_dump`. The dump command itself is injected — these tests cover the
parts that can silently rot: naming, integrity verification, retention.
"""

import gzip
import io
import json
import sys
import tarfile
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


# ---------------------------------------------------------------------------
# Restore drill: a backup that has never been restored is not a backup.
# ---------------------------------------------------------------------------

class FakeRunner:
    """Records commands; returns scripted (returncode, stdout) per call."""

    def __init__(self, table_count=7, fail_on_restore=False):
        self.calls = []
        self.table_count = table_count
        self.fail_on_restore = fail_on_restore

    def __call__(self, cmd, stdin=None):
        joined = " ".join(cmd)
        self.calls.append((joined, stdin is not None))
        if "SELECT count(*)" in joined:
            return 0, str(self.table_count).encode()
        if stdin is not None and self.fail_on_restore:
            return 1, b"restore exploded"
        return 0, b""


def _dump_file(tmp_path):
    return _write_backup(tmp_path, "20260805-031700",
                         b"-- PostgreSQL database dump\nCREATE TABLE t (id int);\n")


def test_restore_drill_passes_and_cleans_up(tmp_path):
    from scripts.prod_backup import verify_restore

    runner = FakeRunner(table_count=7)
    count = verify_restore(_dump_file(tmp_path), runner)
    assert count == 7
    joined = [c for c, _ in runner.calls]
    assert any("CREATE DATABASE restore_check" in c for c in joined)
    assert any(fed_stdin for _, fed_stdin in runner.calls)  # dump piped in
    # scratch DB dropped both before (IF EXISTS) and after
    assert sum("DROP DATABASE" in c for c in joined) >= 2


def test_restore_drill_fails_on_suspicious_table_count(tmp_path):
    from scripts.prod_backup import verify_restore

    runner = FakeRunner(table_count=0)
    with pytest.raises(RuntimeError):
        verify_restore(_dump_file(tmp_path), runner)
    # cleanup still happened
    assert any("DROP DATABASE" in c for c, _ in runner.calls[-1:])


def test_restore_drill_fails_when_restore_errors(tmp_path):
    from scripts.prod_backup import verify_restore

    runner = FakeRunner(fail_on_restore=True)
    with pytest.raises(RuntimeError):
        verify_restore(_dump_file(tmp_path), runner)


# ---------------------------------------------------------------------------
# Registry snapshot: registry.json is worthless without the artifact dirs it
# names, so the tarball has to carry both (PRD R17).
# ---------------------------------------------------------------------------

def _write_registry(root: Path, versions, active=None, history=None) -> dict:
    """Build a registry root shaped like ModelRegistry's: an index plus one
    artifact directory per registered version."""
    root.mkdir(parents=True, exist_ok=True)
    for version_id in versions:
        artifact_dir = root / version_id
        artifact_dir.mkdir(exist_ok=True)
        (artifact_dir / "model.pkl").write_bytes(b"weights of " + version_id.encode())
    index = {
        "versions": {v: {"version_id": v} for v in versions},
        "active": active,
        "history": list(history or []),
        "rejected": [],
    }
    (root / "registry.json").write_text(json.dumps(index))
    return index


def _make_registry_tarball(directory: Path, stamp: str, members: dict) -> Path:
    from scripts.prod_backup import REGISTRY_PREFIX, REGISTRY_SUFFIX

    path = directory / f"{REGISTRY_PREFIX}{stamp}{REGISTRY_SUFFIX}"
    with tarfile.open(path, "w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return path


def test_backup_registry_writes_archive_with_index_and_artifacts(tmp_path):
    from scripts.prod_backup import REGISTRY_PREFIX, backup_registry

    registry_dir = tmp_path / "registry"
    _write_registry(registry_dir, ["20260801-a"], active="20260801-a")

    target = backup_registry(
        registry_dir=registry_dir,
        backup_dir=tmp_path / "backups",
        keep_days=14,
        now=NOW,
    )

    assert target.name == f"{REGISTRY_PREFIX}20260805-031700.tar.gz"
    with tarfile.open(target, "r:gz") as tar:
        names = tar.getnames()
        assert "registry.json" in names
        assert "20260801-a/model.pkl" in names


def test_backup_registry_archives_every_version_in_the_index(tmp_path):
    from scripts.prod_backup import backup_registry

    registry_dir = tmp_path / "registry"
    # prune(keep=N) leaves unprotected versions in the index, so "active plus
    # history" is not the same set as "everything the index names".
    _write_registry(
        registry_dir,
        ["v-active", "v-history", "v-orphan"],
        active="v-active",
        history=["v-history"],
    )

    target = backup_registry(
        registry_dir=registry_dir,
        backup_dir=tmp_path / "backups",
        keep_days=14,
        now=NOW,
    )

    with tarfile.open(target, "r:gz") as tar:
        names = tar.getnames()
    for version_id in ("v-active", "v-history", "v-orphan"):
        assert f"{version_id}/model.pkl" in names


def test_backup_registry_uses_the_index_it_read_not_a_later_one(tmp_path):
    from scripts.prod_backup import _write_registry_archive as real_writer
    from scripts.prod_backup import backup_registry

    registry_dir = tmp_path / "registry"
    _write_registry(registry_dir, ["v-old"], active="v-old")
    index_path = registry_dir / "registry.json"

    def promoting_writer(partial, index_bytes, artifact_dirs):
        # A promotion landing mid-run must not reach the archive: the version
        # it names has no artifact directory in this tarball.
        (registry_dir / "v-new").mkdir()
        index_path.write_text(json.dumps({
            "versions": {"v-old": {}, "v-new": {}},
            "active": "v-new",
            "history": ["v-old"],
            "rejected": [],
        }))
        real_writer(partial, index_bytes, artifact_dirs)

    target = backup_registry(
        registry_dir=registry_dir,
        backup_dir=tmp_path / "backups",
        keep_days=14,
        now=NOW,
        writer=promoting_writer,
    )

    with tarfile.open(target, "r:gz") as tar:
        names = tar.getnames()
        archived = json.loads(tar.extractfile("registry.json").read().decode())
    assert archived["active"] == "v-old"
    assert "v-new" not in archived["versions"]
    assert names[-1] == "registry.json"


def test_backup_registry_raises_on_missing_registry_root(tmp_path):
    from scripts.prod_backup import backup_registry

    backup_dir = tmp_path / "backups"
    with pytest.raises(RuntimeError):
        backup_registry(
            registry_dir=tmp_path / "nope",
            backup_dir=backup_dir,
            keep_days=14,
            now=NOW,
        )
    assert list(tmp_path.rglob("*.tar.gz")) == []
    assert list(tmp_path.rglob("*.partial")) == []


def test_backup_registry_raises_on_registry_root_without_registry_json(tmp_path):
    from scripts.prod_backup import backup_registry

    indexless = tmp_path / "indexless"
    (indexless / "20260801-a").mkdir(parents=True)
    empty = tmp_path / "empty"
    empty.mkdir()

    for registry_dir in (indexless, empty):
        with pytest.raises(RuntimeError):
            backup_registry(
                registry_dir=registry_dir,
                backup_dir=tmp_path / "backups",
                keep_days=14,
                now=NOW,
            )
    assert list(tmp_path.rglob("*.tar.gz")) == []
    assert list(tmp_path.rglob("*.partial")) == []


def test_backup_registry_leaves_no_partial_or_target_on_failure(tmp_path):
    from scripts.prod_backup import backup_registry

    registry_dir = tmp_path / "registry"
    _write_registry(registry_dir, ["20260801-a"], active="20260801-a")
    backup_dir = tmp_path / "backups"

    def failing_writer(partial, index_bytes, artifact_dirs):
        partial.write_bytes(b"half a tarball")
        raise RuntimeError("disk went away")

    with pytest.raises(RuntimeError):
        backup_registry(
            registry_dir=registry_dir,
            backup_dir=backup_dir,
            keep_days=14,
            now=NOW,
            writer=failing_writer,
        )

    assert list(backup_dir.glob("*.tar.gz")) == []
    assert list(backup_dir.glob("*.partial")) == []


def test_verify_registry_archive_accepts_a_registry_that_has_promoted_nothing(tmp_path):
    """Replaces an earlier test that required a non-null active version.

    That rule came from the design, but it makes the nightly cron report
    BACKUP FAILED every night on a host that has not promoted a model yet. A
    registry with no active version is a legitimate pre-promotion state, and a
    backup tool that cries wolf gets ignored. Integrity is still enforced by
    the every-listed-version check below.
    """
    from scripts.prod_backup import verify_registry_archive

    good = _make_registry_tarball(tmp_path, "20260805-031700", {
        "v-a/model.pkl": b"weights",
        "registry.json": json.dumps({"versions": {"v-a": {}}, "active": "v-a"}).encode(),
    })
    assert verify_registry_archive(good) is True

    headless = _make_registry_tarball(tmp_path, "20260805-031701", {
        "v-a/model.pkl": b"weights",
        "registry.json": json.dumps({"versions": {"v-a": {}}, "active": None}).encode(),
    })
    assert verify_registry_archive(headless) is True


def test_verify_registry_archive_rejects_index_version_with_no_archived_artifact_dir(tmp_path):
    from scripts.prod_backup import verify_registry_archive

    torn = _make_registry_tarball(tmp_path, "20260805-031702", {
        "v-a/model.pkl": b"weights",
        "registry.json": json.dumps(
            {"versions": {"v-a": {}, "v-b": {}}, "active": "v-b"}
        ).encode(),
    })
    assert verify_registry_archive(torn) is False

    indexless = tmp_path / "aif-registry-20260805-031703.tar.gz"
    with tarfile.open(indexless, "w:gz"):
        pass
    assert verify_registry_archive(indexless) is False


def test_prune_old_backups_is_prefix_scoped(tmp_path):
    from scripts.prod_backup import REGISTRY_PREFIX, REGISTRY_SUFFIX

    old_db = _write_backup(tmp_path, "20260720-031700")
    old_registry = _make_registry_tarball(tmp_path, "20260720-031700", {"registry.json": b"{}"})

    removed = prune_old_backups(
        tmp_path, keep_days=14, now=NOW,
        prefix=REGISTRY_PREFIX, suffix=REGISTRY_SUFFIX,
    )
    assert removed == [old_registry.name]
    assert not old_registry.exists()
    assert old_db.exists()

    fresh_registry = _make_registry_tarball(tmp_path, "20260720-031701", {"registry.json": b"{}"})
    removed = prune_old_backups(tmp_path, keep_days=14, now=NOW)
    assert removed == [old_db.name]
    assert not old_db.exists()
    assert fresh_registry.exists()


def _fake_dump_cmd():
    return [sys.executable, "-c", "print('-- PostgreSQL database dump'); print('SELECT 1;')"]


def test_main_exits_nonzero_when_registry_backup_fails_after_pg_dump_succeeds(tmp_path, monkeypatch, capsys):
    import scripts.prod_backup as mod

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(mod, "DEFAULT_DUMP_CMD", _fake_dump_cmd())
    monkeypatch.setattr(sys, "argv", [
        "prod_backup.py",
        "--backup-dir", str(backup_dir),
        "--registry-dir", str(tmp_path / "no-such-registry"),
        "--skip-restore-drill",
    ])

    assert mod.main() == 1

    captured = capsys.readouterr()
    assert "BACKUP FAILED" in captured.err
    assert len(list(backup_dir.glob(f"{PREFIX}*.sql.gz"))) == 1
    assert list(backup_dir.glob("*.tar.gz")) == []


def test_main_run_line_reports_registry_archive_size(tmp_path, monkeypatch, capsys):
    import scripts.prod_backup as mod

    backup_dir = tmp_path / "backups"
    registry_dir = tmp_path / "registry"
    _write_registry(registry_dir, ["v-a", "v-b"], active="v-b", history=["v-a"])
    monkeypatch.setattr(mod, "DEFAULT_DUMP_CMD", _fake_dump_cmd())
    monkeypatch.setattr(sys, "argv", [
        "prod_backup.py",
        "--backup-dir", str(backup_dir),
        "--registry-dir", str(registry_dir),
        "--skip-restore-drill",
    ])

    assert mod.main() == 0

    archives = list(backup_dir.glob(f"{mod.REGISTRY_PREFIX}*{mod.REGISTRY_SUFFIX}"))
    dumps = list(backup_dir.glob(f"{PREFIX}*.sql.gz"))
    assert len(archives) == 1 and len(dumps) == 1

    registry_stamp = archives[0].name[len(mod.REGISTRY_PREFIX):-len(mod.REGISTRY_SUFFIX)]
    db_stamp = dumps[0].name[len(PREFIX):-len(".sql.gz")]
    assert registry_stamp == db_stamp

    size_kb = archives[0].stat().st_size // 1024
    run_lines = [ln for ln in capsys.readouterr().out.splitlines() if "registry backup ok" in ln]
    assert len(run_lines) == 1
    assert f"({size_kb} KB)" in run_lines[0]


def test_registry_with_no_active_version_still_backs_up(tmp_path):
    from scripts.prod_backup import REGISTRY_PREFIX, backup_registry

    """A registry that exists but has promoted nothing is a legitimate
    pre-promotion state, not a corrupt one. Refusing to snapshot it would make
    the nightly cron report BACKUP FAILED every night on a fresh host, which is
    the cry-wolf failure this project keeps having to undo."""
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "registry.json").write_text(
        json.dumps({"versions": {}, "active": None, "history": [], "rejected": []})
    )
    backups = tmp_path / "backups"
    backups.mkdir()

    archive = backup_registry(registry, backups, keep_days=14)

    assert archive.exists()
    assert archive.name.startswith(REGISTRY_PREFIX)


def test_registry_archive_still_requires_every_listed_version(tmp_path):
    """Relaxing the active-version rule must not relax the real integrity
    check: an index naming a version with no archived artifacts still fails."""
    from scripts.prod_backup import verify_registry_archive

    orphaned = _make_registry_tarball(tmp_path, "20260805-031702", {
        "registry.json": json.dumps({"versions": {"v-a": {}}, "active": "v-a"}).encode(),
    })
    assert verify_registry_archive(orphaned) is False
