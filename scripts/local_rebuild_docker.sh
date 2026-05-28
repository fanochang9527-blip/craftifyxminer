#!/usr/bin/env bash
# 本地 docker-compose：删卷 → 重建库（initdb 自动执行 schema.sql + indexes.sql）→ admin → 种子
# 前置：Docker Desktop 已启动；项目根目录 .env 已配置 DB_PASSWORD / DATABASE_URL
#
# 用法：
#   cd 项目根目录
#   bash scripts/local_rebuild_docker.sh              # 交互确认后执行
#   CONFIRM=yes bash scripts/local_rebuild_docker.sh   # CI/无人值守（跳过确认）
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$PROJECT_DIR/.env"
  set +a
fi

PGU="${POSTGRES_USER:-miner}"
PGD="${POSTGRES_DB:-craftifyx_miner}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-Admin123}"

if ! docker info &>/dev/null; then
  echo "错误：无法连接 Docker。请先启动 Docker Desktop，再重试。"
  exit 1
fi

if [[ "${CONFIRM:-}" != "yes" ]]; then
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "即将执行：docker compose down -v（删除本地 Postgres 卷，库内数据全部清空）"
  echo "然后：重建容器（initdb 自动执行 schema.sql + indexes.sql）、创建管理员、从 xlsx 导入种子"
  echo "管理员默认：$ADMIN_USER / （环境变量 ADMIN_PASS，默认 Admin123）"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  read -r -p "确认继续请输入大写 YES: " _ack
  if [[ "${_ack}" != "YES" ]]; then
    echo "已取消。"
    exit 1
  fi
fi

echo "[1/4] docker compose down -v ..."
docker compose down -v

echo "[2/4] docker compose build --no-cache && up -d ..."
docker compose build --no-cache
docker compose up -d

echo "[3/4] Wait for Postgres (initdb will auto-run schema.sql + indexes.sql) ..."
for _ in $(seq 1 45); do
  docker compose exec -T db pg_isready -U "$PGU" -d "$PGD" &>/dev/null && break
  sleep 2
done

echo "[4/4] create-admin + seed_import (含后处理: 深度抓取 → 特征计算 → 模型训练) ..."
docker compose run --rm server python -m auth.manage create-admin --username "$ADMIN_USER" --password "$ADMIN_PASS"
docker compose run --rm server python -m pipeline.seed_import \
  --xlsx "/app/data/创作者账号链接及销量收集.xlsx"

echo "Health:"
curl -sf "http://127.0.0.1:${FLASK_PORT:-5000}/health" && echo ""
echo "Done."
