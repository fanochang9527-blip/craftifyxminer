#!/usr/bin/env bash
#
# Growth Score 功能增量部署脚本（本地适配版）
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env"

# ──────────────────────────────────────────────
# 1. 加载环境变量
# ──────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  err ".env not found: $ENV_FILE"
  exit 1
fi
set -a
source "$ENV_FILE"
set +a
: "${DATABASE_URL:?DATABASE_URL is required in .env}"

# ──────────────────────────────────────────────
# 2. 应用数据库变更
# ──────────────────────────────────────────────
apply_schema() {
  log "Applying schema changes (incremental)..."

  if ! command -v psql &>/dev/null; then
    err "psql not found. Please install PostgreSQL client."
    exit 1
  fi

  if ! psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$PROJECT_DIR/db/schema.sql" >/dev/null; then
    err "Schema application failed"
    exit 1
  fi

  log "Schema applied successfully"
}

# ──────────────────────────────────────────────
# 3. 构建新镜像
# ──────────────────────────────────────────────
build_image() {
  log "Building new Docker image..."
  docker compose -f "$COMPOSE_FILE" build server
  log "Build complete"
}

# ──────────────────────────────────────────────
# 4. 存量回填
# ──────────────────────────────────────────────
backfill_snapshots() {
  log "Backfilling follower snapshots for existing creators..."

  if docker compose -f "$COMPOSE_FILE" run --rm server \
    python scripts/backfill_snapshots.py; then
    log "Snapshot backfill complete"
  else
    err "Snapshot backfill failed"
    exit 1
  fi
}

# ──────────────────────────────────────────────
# 5. 启动服务
# ──────────────────────────────────────────────
start_services() {
  log "Starting services..."
  docker compose -f "$COMPOSE_FILE" up -d
  log "Services started"
}

# ──────────────────────────────────────────────
# 6. 健康检查
# ──────────────────────────────────────────────
health_check() {
  log "Waiting for services to be ready..."
  sleep 5

  local health_url="http://localhost:5000/health"
  local max_retries=12
  local retry=0

  while [[ $retry -lt $max_retries ]]; do
    if curl -fsS "$health_url" >/dev/null 2>&1; then
      log "Health check passed: $health_url"
      return 0
    fi
    warn "Health check retry $((retry + 1))/$max_retries..."
    sleep 5
    retry=$((retry + 1))
  done

  err "Health check failed after $max_retries retries"
  return 1
}

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
main() {
  echo ""
  echo "=========================================="
  echo "  Growth Score — Incremental Deployment"
  echo "=========================================="
  echo ""

  cd "$PROJECT_DIR"

  apply_schema
  build_image
  backfill_snapshots
  start_services
  health_check

  echo ""
  log "Deployment complete!"
  echo ""
  echo "Next steps:"
  echo "  - Daily cron will run follower_refresh at 06:00 and growth_monitor at 11:00"
  echo "  - Verify: curl http://<ECS_IP>/health"
  echo ""
}

main "$@"
