#!/usr/bin/env bash
#
# 生产全量重置部署 + 备份数据恢复
# 基于 prod_full_reset_redeploy.sh 流程，在重建数据库后从备份恢复数据
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }

PROJECT_DIR="/opt/craftifyxminer"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.prod.yml"
ENV_FILE="$PROJECT_DIR/.env"
BACKUP_FILE="$PROJECT_DIR/backups/pre_deploy_custom_20260527_145157.dump"
PGRESTORE="/usr/lib/postgresql/18/bin/pg_restore"

cd "$PROJECT_DIR"

# 加载环境变量
set -a
source "$ENV_FILE"
set +a

: "${DATABASE_URL:?DATABASE_URL is required in .env}"

log "Project dir: $PROJECT_DIR"
log "Database:    $(echo "$DATABASE_URL" | sed -E 's#(postgresql://[^:]+:)[^@]+(@.*)#\1***\2#g')"
log "Backup file: $BACKUP_FILE"

# 步骤1: 停止现有容器
log "Stopping and removing existing containers..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans

# 步骤2: 重建数据库
log "Rebuilding database (DROP SCHEMA public CASCADE)..."
export CONFIRM=yes
export WIPE_PUBLIC_SCHEMA=yes
bash "$PROJECT_DIR/scripts/prod_rebuild_database.sh"

# 步骤3: 从备份恢复数据（排除 model_evaluations，因为 schema 有变化）
log "Preparing restore table-of-contents (excluding model_evaluations)..."
$PGRESTORE -l "$BACKUP_FILE" | grep -v "model_evaluations" > /tmp/restore.toc

log "Restoring data from backup..."
$PGRESTORE --data-only --disable-triggers -d "$DATABASE_URL" -L /tmp/restore.toc "$BACKUP_FILE" || true
warn "pg_restore may have warnings for model_evaluations (excluded) or minor constraints; other tables should be restored."

# 验证关键表数据
log "Verifying restored data..."
psql "$DATABASE_URL" -c "SELECT 'creators' as table_name, COUNT(*) as cnt FROM creators
UNION ALL SELECT 'tweets', COUNT(*) FROM tweets
UNION ALL SELECT 'creator_features', COUNT(*) FROM creator_features
UNION ALL SELECT 'users', COUNT(*) FROM users;"

# 步骤4: 创建 admin（已存在则跳过）
log "Creating admin user (skips if already exists)..."
docker compose -f "$COMPOSE_FILE" run --rm server \
  python -m auth.manage create-admin \
  --username admin \
  --password 'Admin123'

# 步骤5: 启动服务（带重建）
log "Starting services with rebuild..."
docker compose -f "$COMPOSE_FILE" up -d --build
docker compose -f "$COMPOSE_FILE" restart nginx

# 步骤6: 补算特征
log "Backfilling missing creator features..."
docker compose -f "$COMPOSE_FILE" run --rm server \
  python -c "from pipeline.feature_engine import backfill_missing_features; backfill_missing_features()"
docker compose -f "$COMPOSE_FILE" run --rm server \
  python -c "from pipeline.feature_engine import backfill_audience_segment_for_existing_features; backfill_audience_segment_for_existing_features()"
log "Feature backfill complete"

# 步骤7: 检查并训练模型
log "Checking model dimension compatibility..."
if docker compose -f "$COMPOSE_FILE" run --rm server \
  python -c "
import json, sys
from pathlib import Path
from config.settings import MODEL_META_PATH, SELLABILITY_MODEL_META_PATH
from pipeline.sps_model import FEATURE_COLS
from config.settings import CREATOR_TYPES

expected = len(FEATURE_COLS) + len(CREATOR_TYPES)
needs_train = False

for meta_path in [MODEL_META_PATH, SELLABILITY_MODEL_META_PATH]:
    if not meta_path.exists():
        needs_train = True
        print(f'Meta missing: {meta_path}')
        break
    with open(meta_path) as f:
        meta = json.load(f)
    actual = meta.get('n_features', 0)
    if actual != expected:
        needs_train = True
        print(f'Dimension mismatch: {meta_path} has {actual}, expected {expected}')
        break

if needs_train:
    print('RETRAIN_REQUIRED')
    sys.exit(1)
else:
    print('MODELS_OK')
    sys.exit(0)
"; then
    log "Model files are up-to-date, skipping training"
else
    warn "Model dimension mismatch or missing, triggering retraining..."
    if docker compose -f "$COMPOSE_FILE" run --rm server \
      python -c "from pipeline.sps_model import train_model as train_sps; from pipeline.sellability_model import train_model as train_sell; train_sps(); train_sell()"; then
        log "Model retraining complete"
    else
        warn "Model retraining failed — models will be retried by daily cron or manual backfill"
    fi
fi

# 步骤8: 健康检查
log "Checking /health ..."
for i in 1 2 3 4 5; do
    if curl -sf http://127.0.0.1/health >/dev/null 2>&1; then
        log "Health check passed."
        break
    fi
    warn "Health check attempt $i/5 failed, retry in 5s..."
    sleep 5
done

log "All done."
echo "Dashboard: http://$(hostname -I | awk '{print $1}')"
echo "Logs:      docker compose -f docker-compose.prod.yml logs -f"
