"""
Backup freshness for /health/detailed.

The nightly backup script (scripts/prod_backup.py) writes
aif-db-YYYYmmdd-HHMMSS.sql.gz files on the host; the directory is mounted
read-only into the API container and named via BACKUP_STATUS_DIR. Freshness
is judged from the filename timestamp, not mtime (mtimes lie after copies).
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

PREFIX = "aif-db-"
STAMP_FORMAT = "%Y%m%d-%H%M%S"
# Nightly cadence plus generous slack: anything older means a broken pipeline.
MAX_AGE_HOURS = 26


def backup_status(
    directory: Optional[str],
    now: Optional[datetime] = None,
    max_age_hours: float = MAX_AGE_HOURS,
) -> Dict[str, Any]:
    if not directory:
        return {"status": "not_configured", "latest_backup": None, "age_hours": None}

    now = now or datetime.utcnow()
    newest_name = None
    newest_stamp = None
    base = Path(directory)
    if base.is_dir():
        for path in base.glob(f"{PREFIX}*.sql.gz"):
            stamp_text = path.name[len(PREFIX):-len(".sql.gz")]
            try:
                stamp = datetime.strptime(stamp_text, STAMP_FORMAT)
            except ValueError:
                continue
            if newest_stamp is None or stamp > newest_stamp:
                newest_stamp = stamp
                newest_name = path.name

    if newest_stamp is None:
        return {"status": "missing", "latest_backup": None, "age_hours": None}

    age_hours = (now - newest_stamp).total_seconds() / 3600
    return {
        "status": "healthy" if age_hours <= max_age_hours else "stale",
        "latest_backup": newest_name,
        "age_hours": round(age_hours, 1),
    }


def backup_status_from_env() -> Dict[str, Any]:
    return backup_status(os.environ.get("BACKUP_STATUS_DIR"))
