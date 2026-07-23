#!/usr/bin/env bash
# Daily database backup with rotation (issue #12, PRD R17).
#
# Cron example (2:15 AM daily):
#   15 2 * * * /app/scripts/backup_db.sh >> /var/log/aif-backup.log 2>&1
#
# Restore procedure (verified — see docs/RUNBOOK.md):
#   gunzip -c backups/ai_forecasting-<stamp>.sql.gz | \
#     psql "$DATABASE_URL_PSQL"
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
# POSTGRES_PORT tracks the compose host binding (see docker-compose.yml).
PGURL="${DATABASE_URL_PSQL:-postgresql://user:password@localhost:${POSTGRES_PORT:-5432}/ai_forecasting}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
FILE="$BACKUP_DIR/ai_forecasting-$STAMP.sql.gz"

pg_dump --no-owner --no-privileges "$PGURL" | gzip > "$FILE"
echo "backup written: $FILE ($(du -h "$FILE" | cut -f1))"

# Rotate: delete backups older than KEEP_DAYS.
find "$BACKUP_DIR" -name 'ai_forecasting-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
echo "backups on disk: $(ls "$BACKUP_DIR" | wc -l | tr -d ' ')"
