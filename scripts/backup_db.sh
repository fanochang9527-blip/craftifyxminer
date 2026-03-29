#!/usr/bin/env bash
# Database backup script — run via crontab: 0 3 * * * /opt/craftifyxminer/scripts/backup_db.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/craftifyx_miner_${TIMESTAMP}.sql.gz"

echo "[$(date)] Starting database backup..."

pg_dump "$DATABASE_URL" | gzip > "$BACKUP_FILE"

echo "[$(date)] Backup saved to $BACKUP_FILE ($(du -sh "$BACKUP_FILE" | cut -f1))"

echo "[$(date)] Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "craftifyx_miner_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete

echo "[$(date)] Backup complete."
