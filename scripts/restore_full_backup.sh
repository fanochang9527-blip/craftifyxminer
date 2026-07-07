#!/usr/bin/env bash
# 全量恢复备份到当前 RDS（使用临时 PostgreSQL 容器做中间转换）
#
# 用法：
#   cd /opt/craftifyxminer
#   source .env
#   bash scripts/restore_full_backup.sh backups/craftifyx_miner_20260706_152043.sql.gz
#
# 说明：
#   1. 启动临时 PostgreSQL 容器
#   2. 将备份恢复到临时数据库（自动去除 \\restrict）
#   3. 按依赖顺序将各表从临时库导入当前 RDS
#   4. 自动清理临时容器

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_PATH="${1:-}"
PYTHON_CMD="${PYTHON_CMD:-$PROJECT_DIR/.venv/bin/python}"
TEMP_CONTAINER_NAME="temp-postgres-restore"
TEMP_PORT="5434"
TEMP_DB_URL="postgresql://postgres:temp123@127.0.0.1:${TEMP_PORT}/temp_backup"

if [[ -z "$BACKUP_PATH" ]]; then
  echo "Usage: $0 <backup.sql.gz>"
  exit 1
fi

if [[ ! -f "$BACKUP_PATH" ]]; then
  echo "Backup file not found: $BACKUP_PATH"
  exit 1
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is not set"
  exit 1
fi

# 清理可能残留的临时容器
docker rm -f "$TEMP_CONTAINER_NAME" >/dev/null 2>&1 || true

# 启动临时 PostgreSQL
echo "Starting temporary PostgreSQL container..."
docker run -d --name "$TEMP_CONTAINER_NAME" \
  -e POSTGRES_PASSWORD=temp123 \
  -e POSTGRES_DB=temp_backup \
  -v "$PROJECT_DIR/backups:/backups:ro" \
  -p "127.0.0.1:${TEMP_PORT}:5432" \
  postgres:18-alpine

# 确保退出时清理容器
cleanup() {
  echo "Stopping temporary PostgreSQL container..."
  docker rm -f "$TEMP_CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# 等待 PostgreSQL 就绪
echo "Waiting for temp PostgreSQL to be ready..."
for i in $(seq 1 30); do
  if docker exec "$TEMP_CONTAINER_NAME" pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# 将备份恢复到临时数据库（去除 \\restrict 避免 psql 进入 restricted mode）
echo "Restoring backup to temp database..."
BACKUP_BASENAME="$(basename "$BACKUP_PATH")"
docker exec "$TEMP_CONTAINER_NAME" bash -c \
  "gunzip -c /backups/${BACKUP_BASENAME} | sed '/^\\\\restrict/d' | psql -U postgres -d temp_backup"

# 从临时数据库导入到当前 RDS
echo "Copying tables from temp database to current RDS..."
TEMP_DB_URL="$TEMP_DB_URL" "$PYTHON_CMD" "$PROJECT_DIR/scripts/restore_all_tables_from_temp_db.py"

echo "Full backup restore complete."
