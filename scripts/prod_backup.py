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

PREFIX = "aif-db-"
STAMP_FORMAT = "%Y%m%d-%H%M%S"

DEFAULT_DUMP_CMD = [
    "docker", "compose", "-f", "docker-compose.prod.yml",
    "exec", "-T", "postgres",
    "pg_dump", "-U", "aif_user", "ai_forecasting",
]


def backup_filename(now: datetime | None = None) -> str:
    stamp = (now or datetime.utcnow()).strftime(STAMP_FORMAT)
    return f"{PREFIX}{stamp}.sql.gz"


def prune_old_backups(backup_dir: Path, keep_days: int, now: datetime | None = None) -> list:
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


def run_backup(
    backup_dir: Path,
    keep_days: int,
    dump_cmd: list,
    now: datetime | None = None,
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
    args = parser.parse_args()
    try:
        run_backup(Path(args.backup_dir), args.keep_days, DEFAULT_DUMP_CMD)
    except Exception as exc:
        print(f"{datetime.utcnow().isoformat()} BACKUP FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
