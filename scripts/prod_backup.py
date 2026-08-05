#!/usr/bin/env python3
"""
Nightly Postgres backup for the production stack (RUNBOOK §3, PRD R17).

The prod compose exposes no host port for Postgres, so the dump runs through
`docker compose exec -T postgres pg_dump`. Runs from host cron:

    17 3 * * * cd /opt/ai-forecasting && /usr/bin/python3 scripts/prod_backup.py \
        --backup-dir /opt/backups/ai-forecasting >> /var/log/aif-backup.log 2>&1

Fails loudly (nonzero exit, no half-written file) so a broken backup shows
up in the log instead of being discovered during a restore.
"""

import argparse
import gzip
import io
import json
import os
import subprocess
import sys
import tarfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

PREFIX = "aif-db-"
SUFFIX = ".sql.gz"
REGISTRY_PREFIX = "aif-registry-"
REGISTRY_SUFFIX = ".tar.gz"
REGISTRY_INDEX = "registry.json"
STAMP_FORMAT = "%Y%m%d-%H%M%S"

# The cron line cds into the compose project dir, which is also the repo root.
DEFAULT_REGISTRY_DIR = Path(__file__).resolve().parent.parent / "models" / "registry"

DEFAULT_DUMP_CMD = [
    "docker", "compose", "-f", "docker-compose.prod.yml",
    "exec", "-T", "postgres",
    "pg_dump", "-U", "aif_user", "ai_forecasting",
]


def backup_filename(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.utcnow()).strftime(STAMP_FORMAT)
    return f"{PREFIX}{stamp}{SUFFIX}"


def registry_filename(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.utcnow()).strftime(STAMP_FORMAT)
    return f"{REGISTRY_PREFIX}{stamp}{REGISTRY_SUFFIX}"


def prune_old_backups(
    backup_dir: Path,
    keep_days: int,
    now: Optional[datetime] = None,
    prefix: str = PREFIX,
    suffix: str = SUFFIX,
) -> List[str]:
    """Delete backups older than keep_days, judged by the timestamp in the
    filename (mtimes lie after copies). Non-matching files are untouched.

    Scoped by prefix and suffix so pruning one artifact class can never reach
    the other's files, which share the directory and the retention window.
    """
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=keep_days)
    removed = []
    for path in sorted(Path(backup_dir).glob(f"{prefix}*{suffix}")):
        stamp_text = path.name[len(prefix):-len(suffix)]
        try:
            stamp = datetime.strptime(stamp_text, STAMP_FORMAT)
        except ValueError:
            continue
        if stamp < cutoff:
            path.unlink()
            removed.append(path.name)
    return removed


def verify_gzip_sql(path: Path) -> bool:
    """Decompress fully and check it looks like a pg_dump (starts with the
    SQL comment header). Catches truncated, empty, and error-page dumps."""
    try:
        with gzip.open(path, "rb") as fh:
            head = fh.read(64)
            if not head.startswith(b"--"):
                return False
            while fh.read(1024 * 1024):
                pass
        return True
    except (OSError, EOFError):
        return False


PSQL_BASE = [
    "docker", "compose", "-f", "docker-compose.prod.yml",
    "exec", "-T", "postgres",
    "psql", "-U", "aif_user", "-v", "ON_ERROR_STOP=1",
]


def _run_cmd(cmd, stdin=None):
    result = subprocess.run(cmd, input=stdin, capture_output=True)
    return result.returncode, result.stdout


def verify_restore(gz_path: Path, run_cmd=_run_cmd, min_tables: int = 5) -> int:
    """Restore the fresh dump into a scratch database and count its tables.

    A backup that has never been restored is not a backup. Runs entirely in
    the postgres container against a throwaway `restore_check` database,
    which is dropped afterwards regardless of outcome.
    """
    def psql(*args, stdin=None):
        return run_cmd(PSQL_BASE + list(args), stdin=stdin)

    rc, _ = psql("-d", "postgres", "-c", "DROP DATABASE IF EXISTS restore_check")
    if rc != 0:
        raise RuntimeError("restore drill: could not drop stale scratch database")
    rc, _ = psql("-d", "postgres", "-c", "CREATE DATABASE restore_check")
    if rc != 0:
        raise RuntimeError("restore drill: could not create scratch database")
    try:
        with gzip.open(gz_path, "rb") as fh:
            sql = fh.read()
        rc, out = psql("-q", "-d", "restore_check", stdin=sql)
        if rc != 0:
            raise RuntimeError(f"restore drill: restore failed: {out[:200]!r}")
        rc, out = psql(
            "-t", "-d", "restore_check", "-c",
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'",
        )
        if rc != 0:
            raise RuntimeError("restore drill: could not count restored tables")
        count = int(out.strip() or 0)
        if count < min_tables:
            raise RuntimeError(
                f"restore drill: only {count} tables restored (expected >= {min_tables})"
            )
        return count
    finally:
        psql("-d", "postgres", "-c", "DROP DATABASE IF EXISTS restore_check")


def run_backup(
    backup_dir: Path,
    keep_days: int,
    dump_cmd: list,
    now: Optional[datetime] = None,
) -> Path:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / backup_filename(now)
    partial = target.with_suffix(".partial")

    try:
        result = subprocess.run(dump_cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"dump command failed ({result.returncode}): {result.stderr[:300]!r}"
            )
        if not result.stdout.strip():
            raise RuntimeError("dump command produced no output")

        with gzip.open(partial, "wb") as fh:
            fh.write(result.stdout)
        if not verify_gzip_sql(partial):
            raise RuntimeError("backup failed integrity verification")
        os.replace(partial, target)
    except Exception:
        partial.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise

    pruned = prune_old_backups(backup_dir, keep_days, now=now)
    size_kb = target.stat().st_size // 1024
    print(f"{datetime.utcnow().isoformat()} backup ok: {target} ({size_kb} KB), pruned {len(pruned)}")
    return target


def verify_registry_archive(path: Path) -> bool:
    """Check the tarball can rebuild a working registry: a parseable index and
    an artifact directory for every version that index names.

    An index pointing at a directory the archive never captured restores into a
    registry that cannot load its own models.

    A null active version is deliberately NOT a failure. A registry that exists
    but has promoted nothing is a legitimate pre-promotion state, and treating
    it as corrupt would make the nightly cron report BACKUP FAILED every night
    on a fresh host.
    """
    try:
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            if REGISTRY_INDEX not in names:
                return False
            member = tar.extractfile(REGISTRY_INDEX)
            if member is None:
                return False
            index = json.loads(member.read().decode("utf-8"))
            for version_id in index.get("versions", {}):
                if not any(n == version_id or n.startswith(f"{version_id}/") for n in names):
                    return False
        return True
    except (OSError, EOFError, ValueError, tarfile.TarError):
        return False


def _write_registry_archive(partial: Path, index_bytes: bytes, artifact_dirs: List[Path]) -> None:
    with tarfile.open(partial, "w:gz") as tar:
        for artifact_dir in artifact_dirs:
            tar.add(artifact_dir, arcname=artifact_dir.name)
        info = tarfile.TarInfo(REGISTRY_INDEX)
        info.size = len(index_bytes)
        tar.addfile(info, io.BytesIO(index_bytes))


def backup_registry(
    registry_dir: Path,
    backup_dir: Path,
    keep_days: int,
    now: Optional[datetime] = None,
    writer=_write_registry_archive,
) -> Path:
    """Snapshot the model registry as one verified tarball.

    Every version in the index is archived, not just active plus history:
    prune(keep=N) deliberately leaves unprotected versions in the index, and a
    restored index naming an unarchived directory is a broken backup.
    """
    registry_dir = Path(registry_dir)
    index_path = registry_dir / REGISTRY_INDEX
    if not index_path.is_file():
        raise RuntimeError(f"registry snapshot: no {REGISTRY_INDEX} under {registry_dir}")

    # Read the index once and archive that copy: a promotion landing mid-run
    # must not add a version whose directory this archive never captured.
    index_bytes = index_path.read_bytes()
    try:
        index = json.loads(index_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"registry snapshot: unreadable {REGISTRY_INDEX}: {exc}") from exc

    artifact_dirs = []
    for version_id in sorted(index.get("versions", {})):
        artifact_dir = registry_dir / version_id
        if not artifact_dir.is_dir():
            raise RuntimeError(
                f"registry snapshot: version '{version_id}' has no artifact directory"
            )
        artifact_dirs.append(artifact_dir)

    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / registry_filename(now)
    partial = target.with_suffix(".partial")

    try:
        writer(partial, index_bytes, artifact_dirs)
        if not verify_registry_archive(partial):
            raise RuntimeError("registry snapshot failed integrity verification")
        os.replace(partial, target)
    except Exception:
        partial.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise

    pruned = prune_old_backups(
        backup_dir, keep_days, now=now,
        prefix=REGISTRY_PREFIX, suffix=REGISTRY_SUFFIX,
    )
    size_kb = target.stat().st_size // 1024
    print(
        f"{datetime.utcnow().isoformat()} registry backup ok: {target} "
        f"({size_kb} KB), pruned {len(pruned)}"
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--registry-dir", default=str(DEFAULT_REGISTRY_DIR))
    parser.add_argument("--keep-days", type=int, default=14)
    parser.add_argument("--skip-restore-drill", action="store_true")
    args = parser.parse_args()
    try:
        # One stamp for both artifacts so a restore can pair them by name.
        now = datetime.utcnow()
        target = run_backup(Path(args.backup_dir), args.keep_days, DEFAULT_DUMP_CMD, now=now)
        backup_registry(Path(args.registry_dir), Path(args.backup_dir), args.keep_days, now=now)
        if not args.skip_restore_drill:
            tables = verify_restore(target)
            print(f"{datetime.utcnow().isoformat()} restore drill ok: {tables} tables")
    except Exception as exc:
        print(f"{datetime.utcnow().isoformat()} BACKUP FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
