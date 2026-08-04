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
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

PREFIX = "aif-db-"
STAMP_FORMAT = "%Y%m%d-%H%M%S"

DEFAULT_DUMP_CMD = [
    "docker", "compose", "-f", "docker-compose.prod.yml",
    "exec", "-T", "postgres",
    "pg_dump", "-U", "aif_user", "ai_forecasting",
]


def backup_filename(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.utcnow()).strftime(STAMP_FORMAT)
    return f"{PREFIX}{stamp}.sql.gz"


def prune_old_backups(backup_dir: Path, keep_days: int, now: Optional[datetime] = None) -> List[str]:
    """Delete backups older than keep_days, judged by the timestamp in the
    filename (mtimes lie after copies). Non-matching files are untouched."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=keep_days)
    removed = []
    for path in sorted(Path(backup_dir).glob(f"{PREFIX}*.sql.gz")):
        stamp_text = path.name[len(PREFIX):-len(".sql.gz")]
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--keep-days", type=int, default=14)
    parser.add_argument("--skip-restore-drill", action="store_true")
    args = parser.parse_args()
    try:
        target = run_backup(Path(args.backup_dir), args.keep_days, DEFAULT_DUMP_CMD)
        if not args.skip_restore_drill:
            tables = verify_restore(target)
            print(f"{datetime.utcnow().isoformat()} restore drill ok: {tables} tables")
    except Exception as exc:
        print(f"{datetime.utcnow().isoformat()} BACKUP FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
