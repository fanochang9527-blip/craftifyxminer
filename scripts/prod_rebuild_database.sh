#!/usr/bin/env bash
#
# 生产（RDS + docker-compose.prod）删库重建 — 在 ECS 上由运维执行。
# 危险操作：会清空 public schema 或整库。执行前务必 RDS 快照或 pg_dump。
#
# 用法示例:
#   cd /opt/craftifyxminer
#   set -a && source .env && set +a
#   CONFIRM=yes bash scripts/prod_rebuild_database.sh
#
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$PROJECT_DIR/.env"
  set +a
fi

: "${DATABASE_URL:?set DATABASE_URL (source .env)}"

if [[ "${CONFIRM:-}" != "yes" ]]; then
  echo -e "${RED}Refusing to run: set CONFIRM=yes to acknowledge backup + downtime.${NC}"
  exit 1
fi

echo -e "${GREEN}[1/5]${NC} Stopping app containers (prod)..."
docker compose -f docker-compose.prod.yml stop cron server dashboard nginx 2>/dev/null || true

if [[ "${WIPE_PUBLIC_SCHEMA:-}" == "yes" ]]; then
  echo -e "${GREEN}[1b]${NC} WIPE_PUBLIC_SCHEMA=yes — DROP SCHEMA public CASCADE; recreate..."
  U="${POSTGRES_USER:-miner}"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "GRANT ALL ON SCHEMA public TO ${U};"
fi

echo -e "${GREEN}[2/5]${NC} Applying schema.sql + indexes.sql ..."
_run_sql() {
  local file="$1"
  if command -v psql &>/dev/null; then
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$file"
  else
    docker run --rm \
      -v "$PROJECT_DIR/db:/sql:ro" \
      --network host \
      postgres:18-alpine \
      psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "/sql/${file#$PROJECT_DIR/db/}"
  fi
}

_run_sql "$PROJECT_DIR/db/schema.sql"
_run_sql "$PROJECT_DIR/db/indexes.sql"

# 全新数据库（WIPE）时 schema.sql 已是最新，跳过迁移；升级场景执行所有迁移
if [[ "${WIPE_PUBLIC_SCHEMA:-}" == "yes" ]]; then
  echo -e "${GREEN}[2b/5]${NC} WIPE mode — skipping migrations (schema.sql is already up-to-date)"
else
  echo -e "${GREEN}[2b/5]${NC} Applying all migrations ..."
  for mig in "$PROJECT_DIR/db/migrations/"*.sql; do
    if [[ -f "$mig" ]]; then
      echo "  -> $(basename "$mig")"
      _run_sql "$mig"
    fi
  done
fi

echo -e "${GREEN}[3/5]${NC} Done SQL. Next: create admin (interactive credentials):"
echo "  docker compose -f docker-compose.prod.yml run --rm server python -m auth.manage create-admin --username ADMIN --password '...'"

echo -e "${GREEN}[4/5]${NC} Seed import (xlsx or csv inside image under /app/data):"
echo "  docker compose -f docker-compose.prod.yml run --rm server python -m pipeline.seed_import --xlsx '/app/data/创作者账号链接及销量收集.xlsx' --skip-post-pipeline"
echo "  # or: --csv /app/data/creators_seed_from_xlsx.csv --skip-post-pipeline"

echo -e "${GREEN}[5/5]${NC} Start stack:"
echo "  docker compose -f docker-compose.prod.yml up -d --build"
