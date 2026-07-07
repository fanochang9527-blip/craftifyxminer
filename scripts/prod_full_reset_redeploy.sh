#!/usr/bin/env bash
#
# 生产全量重置部署（ECS + RDS）
# 发布标记：20260706
# 适用场景：确认清空 RDS 旧数据并按最新代码全量重建、导入新种子、
#          自动导入合作中作者、深度抓取、清洗 website、补算特征/分数、训练模型、重启服务。
# 变更摘要：
#   - 支持种子文件位于项目根目录，自动复制到 data/
#   - CSV 种子自动清洗 NaN/Inf 空值
#   - 自动导入 data/seed_working.xlsx
#   - 支持从旧备份恢复全部 creators/features（--restore-from-backup）
#   - 自动对合作中作者触发深度抓取
#   - 自动清洗 website（去除社交链接，优先使用 expanded_url 店铺链接）
#   - 全量重新计算 features 与 scores
#   - 模型维度检查 bug 修复（分别校验 SPS/sellability）
#
# 用法示例（交互）:
#   cd /opt/craftifyxminer
#   bash scripts/prod_full_reset_redeploy.sh --branch main --seed-file data/创作者账号链接及销量收集.xlsx
#
# 用法示例（非交互，含备份恢复）:
#   bash scripts/prod_full_reset_redeploy.sh \
#     --non-interactive \
#     --branch main \
#     --seed-file data/creators_seed_from_xlsx.csv \
#     --restore-from-backup backups/craftifyx_miner_20260706_152043.sql.gz \
#     --admin-username admin \
#     --admin-password 'StrongPass123'
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
COMPOSE_FILE="$PROJECT_DIR/docker-compose.prod.yml"
ENV_FILE="$PROJECT_DIR/.env"

BRANCH=""
SEED_FILE=""
RESTORE_FROM_BACKUP=""
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin123}"
NON_INTERACTIVE=0
SKIP_DB_REBUILD=0
SKIP_GIT_PULL=0
SKIP_HEALTHCHECK=0
RELEASE_MARK="20260706"

usage() {
  cat <<'EOF'
生产全量重置部署脚本（会清空 RDS public schema）
发布标记: 20260706

参数:
  --branch <name>            Git 分支名（默认当前分支）
  --seed-file <path>         种子文件路径（支持 .xlsx/.csv，不在 data/ 下会自动复制）
  --restore-from-backup <path>  从旧备份中恢复全部 creators/features（.sql/.sql.gz）
  --admin-username <name>    管理员用户名（默认 admin）
  --admin-password <pwd>     管理员密码（不传则交互输入）
  --non-interactive          非交互模式（必须提供 --seed-file 与 --admin-password）
  --skip-db-rebuild          跳过数据库重建（仅更新代码+重启服务）
  --skip-git-pull            跳过 git fetch/pull
  --skip-healthcheck         跳过 /health 检查
  -h, --help                 显示帮助
EOF
}

prompt_yes_no() {
  local message="$1"
  local default="${2:-N}"
  local ans
  if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    return 0
  fi
  if [[ "$default" == "Y" ]]; then
    read -rp "$message [Y/n]: " ans
    [[ -z "$ans" || "$ans" == "y" || "$ans" == "Y" ]]
  else
    read -rp "$message [y/N]: " ans
    [[ "$ans" == "y" || "$ans" == "Y" ]]
  fi
}

require_cmd() {
  local c="$1"
  if ! command -v "$c" >/dev/null 2>&1; then
    err "Missing required command: $c"
    exit 1
  fi
}

resolve_seed_file() {
  local input="$1"
  local abs
  if [[ "$input" = /* ]]; then
    abs="$input"
  else
    abs="$PROJECT_DIR/$input"
  fi

  if [[ ! -f "$abs" ]]; then
    err "Seed file not found: $abs"
    exit 1
  fi

  local data_prefix="$PROJECT_DIR/data/"
  local rel="${abs#"$PROJECT_DIR/"}"

  # If seed file is outside data/, copy it into data/ so docker can read it
  if [[ "$abs" != "$data_prefix"* ]]; then
    local basename
    basename="$(basename "$abs")"
    local target="$data_prefix$basename"
    cp -f "$abs" "$target"
    log "Copied seed file to $target"
    rel="data/$basename"
  fi

  SEED_FILE="$rel"
}

mask_db_url() {
  local url="$1"
  # 简单脱敏：仅隐藏 password 段
  echo "$url" | sed -E 's#(postgresql://[^:]+:)[^@]+(@.*)#\1***\2#g'
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --branch)
        BRANCH="${2:-}"
        shift 2
        ;;
      --seed-file)
        SEED_FILE="${2:-}"
        shift 2
        ;;
      --restore-from-backup)
        RESTORE_FROM_BACKUP="${2:-}"
        shift 2
        ;;
      --admin-username)
        ADMIN_USERNAME="${2:-}"
        shift 2
        ;;
      --admin-password)
        ADMIN_PASSWORD="${2:-}"
        shift 2
        ;;
      --non-interactive)
        NON_INTERACTIVE=1
        shift
        ;;
      --skip-db-rebuild)
        SKIP_DB_REBUILD=1
        shift
        ;;
      --skip-git-pull)
        SKIP_GIT_PULL=1
        shift
        ;;
      --skip-healthcheck)
        SKIP_HEALTHCHECK=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        err "Unknown arg: $1"
        usage
        exit 1
        ;;
    esac
  done
}

load_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    err ".env not found: $ENV_FILE"
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  : "${DATABASE_URL:?DATABASE_URL is required in .env}"
}

input_admin_password_if_needed() {
  if [[ -n "$ADMIN_PASSWORD" ]]; then
    return
  fi
  if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    err "--non-interactive requires --admin-password"
    exit 1
  fi
  read -rsp "请输入管理员密码（至少 8 位，含字母数字）: " ADMIN_PASSWORD
  echo ""
  if [[ -z "$ADMIN_PASSWORD" ]]; then
    err "管理员密码不能为空"
    exit 1
  fi
}

confirm_destructive_action() {
  if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    return
  fi
  echo ""
  warn "即将执行破坏性操作：DROP SCHEMA public CASCADE（不可恢复）"
  warn "目标数据库：$(mask_db_url "$DATABASE_URL")"
  read -rp "请输入 I_UNDERSTAND 继续: " token
  if [[ "$token" != "I_UNDERSTAND" ]]; then
    err "确认口令不匹配，已取消。"
    exit 1
  fi
}

git_sync() {
  if [[ "$SKIP_GIT_PULL" -eq 1 ]]; then
    warn "Skip git pull as requested."
    return
  fi

  if [[ -z "$BRANCH" ]]; then
    BRANCH="$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD)"
  fi

  if [[ "$NON_INTERACTIVE" -eq 0 ]]; then
    log "Current branch: $BRANCH"
    if ! prompt_yes_no "执行 git fetch + git pull origin $BRANCH ?" "Y"; then
      err "用户取消 git 同步。"
      exit 1
    fi
  fi

  git -C "$PROJECT_DIR" fetch origin
  git -C "$PROJECT_DIR" pull origin "$BRANCH"
  log "Git synced. HEAD=$(git -C "$PROJECT_DIR" rev-parse --short HEAD)"
}

rebuild_database() {
  log "Rebuilding database (wipe public schema)..."
  (
    cd "$PROJECT_DIR"
    export CONFIRM=yes
    export WIPE_PUBLIC_SCHEMA=yes
    bash scripts/prod_rebuild_database.sh
  )
}

create_admin() {
  log "Ensuring admin user exists with provided password: $ADMIN_USERNAME"
  # create-admin is idempotent; if admin exists from backup, reset password to ensure
  # the user-specified password is active
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -m auth.manage create-admin \
    --username "$ADMIN_USERNAME" \
    --password "$ADMIN_PASSWORD" || true
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -m auth.manage reset-password \
    --username "$ADMIN_USERNAME" \
    --password "$ADMIN_PASSWORD" || true
}

fix_csv_nulls_if_needed() {
  local ext="${SEED_FILE##*.}"
  if [[ "$ext" != "csv" && "$ext" != "CSV" ]]; then
    return 0
  fi

  log "Preprocessing CSV seed file to fix NaN/Inf values..."
  local host_path="$PROJECT_DIR/$SEED_FILE"

  if ! command -v python3 >/dev/null 2>&1; then
    warn "python3 not found on host, skipping CSV NaN cleanup (ensure seed_file.csv is clean)"
    return 0
  fi

  python3 - "$host_path" <<'PY'
import sys
from pathlib import Path
import pandas as pd

path = Path(sys.argv[1])
df = pd.read_csv(path, dtype=str, keep_default_na=False)

# Replace literal 'nan', 'NaN', 'inf', '-inf', empty NaN with safe defaults
for col in df.columns:
    lower = col.lower()
    # Numeric sales/gmv/follower columns
    if any(k in lower for k in ["sales", "gmv", "follower", "count", "score", "price", "qty", "num"]):
        df[col] = df[col].replace({"": "0", "nan": "0", "NaN": "0", "inf": "0", "-inf": "0", "None": "0"})
    else:
        df[col] = df[col].replace({"nan": "", "NaN": "", "inf": "", "-inf": "", "None": ""})

# Extra: known columns that should be numeric
num_cols = ["30天销量", "30天GMV", "总销量", "总GMV", "粉丝数"]
for col in num_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int).astype(str)

df.to_csv(path, index=False)
print(f"Cleaned CSV: {path}")
PY
}

import_seeds() {
  local ext="${SEED_FILE##*.}"
  local container_path="/app/${SEED_FILE}"

  case "$ext" in
    xlsx|XLSX)
      log "Importing seed xlsx: $container_path"
      docker compose -f "$COMPOSE_FILE" run --rm server \
        python -m pipeline.seed_import \
        --xlsx "$container_path"
      ;;
    csv|CSV)
      log "Importing seed csv: $container_path"
      docker compose -f "$COMPOSE_FILE" run --rm server \
        python -m pipeline.seed_import \
        --csv "$container_path"
      ;;
    *)
      err "Unsupported seed file extension: .$ext (use .xlsx or .csv)"
      exit 1
      ;;
  esac
}

import_seed_working() {
  local xlsx="$PROJECT_DIR/data/seed_working.xlsx"
  if [[ ! -f "$xlsx" ]]; then
    warn "data/seed_working.xlsx not found, skipping working-seed import"
    return 0
  fi

  log "Importing working creators from data/seed_working.xlsx..."
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -m pipeline.seed_working_import \
    --xlsx "/app/data/seed_working.xlsx"
}

resolve_restore_backup() {
  local input="$1"
  local abs
  if [[ "$input" = /* ]]; then
    abs="$input"
  else
    abs="$PROJECT_DIR/$input"
  fi

  if [[ ! -f "$abs" ]]; then
    err "Backup file not found: $abs"
    exit 1
  fi

  RESTORE_FROM_BACKUP="$abs"
}

resolve_restore_backup_if_needed() {
  if [[ -z "$RESTORE_FROM_BACKUP" ]]; then
    return 0
  fi
  resolve_restore_backup "$RESTORE_FROM_BACKUP"
}

restore_from_backup() {
  if [[ -z "$RESTORE_FROM_BACKUP" ]]; then
    return 0
  fi

  log "Restoring full backup (all tables): $RESTORE_FROM_BACKUP"
  bash "$PROJECT_DIR/scripts/restore_full_backup.sh" "$RESTORE_FROM_BACKUP"
  log "Full backup restored"
}

scrape_seed_working() {
  log "Triggering deep scrape for working creators..."
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -c "
from db.connection import fetch_all
from pipeline.deep_scrape import trigger_seed_deep_scrape

rows = fetch_all(\"\"\"
    SELECT username FROM creators
    WHERE discovery_strategy = 'seed_working_import'
    ORDER BY username
\"\"\")
usernames = [r['username'] for r in rows if r['username']]
log_lines = [f'Found {len(usernames)} working creators to deep scrape']
for line in log_lines:
    print(line)
if not usernames:
    print('No working creators found, skipping deep scrape')
else:
    result = trigger_seed_deep_scrape(usernames)
    print(f'Deep scrape result: {result}')
"
}

start_services() {
  log "Starting services with rebuild..."
  docker compose -f "$COMPOSE_FILE" up -d --build
}

apply_migrations() {
  log "Applying database migrations (incremental, safe to re-run)..."
  local mig_dir="$PROJECT_DIR/db/migrations"
  if [[ -d "$mig_dir" ]]; then
    for mig in "$mig_dir"/*.sql; do
      if [[ -f "$mig" ]]; then
        log "  -> $(basename "$mig")"
        if command -v psql &>/dev/null; then
          psql "$DATABASE_URL" -v ON_ERROR_STOP=0 -f "$mig" >/dev/null 2>&1 || true
        else
          docker run --rm \
            -v "$PROJECT_DIR/db:/sql:ro" \
            --network host \
            postgres:18-alpine \
            psql "$DATABASE_URL" -v ON_ERROR_STOP=0 -f "/sql/migrations/$(basename "$mig")" >/dev/null 2>&1 || true
        fi
      fi
    done
  fi
  log "Migrations applied"
}

backfill_features() {
  log "Backfilling missing creator features..."
  # 1) 给有 tweets 但完全没有 features 的创作者计算全部特征
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -c "from pipeline.feature_engine import backfill_missing_features; backfill_missing_features()"
  # 2) 给已有 features 但缺少 audience_segment_score 的存量记录补算新列
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -c "from pipeline.feature_engine import backfill_audience_segment_for_existing_features; backfill_audience_segment_for_existing_features()"
  log "Feature backfill complete"
}

recompute_all_features_and_scores() {
  log "Recomputing features (creators with tweets) and scores (creators with features)..."
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -c "
from db.connection import fetch_all
from pipeline.feature_engine import compute_features_for_creator
from pipeline.sps_scorer import score_creator

# Recompute features for creators that have tweets (imported backup creators without tweets keep their restored features)
feature_rows = fetch_all('''SELECT DISTINCT c.id FROM creators c
                            JOIN tweets t ON t.creator_id = c.id
                            ORDER BY c.id''')
feature_ok = 0
feature_fail = 0
for row in feature_rows:
    cid = row['id']
    try:
        compute_features_for_creator(cid)
        feature_ok += 1
    except Exception as e:
        feature_fail += 1
        print(f'Feature failed for {cid}: {e}')
print(f'Features: {feature_ok} ok, {feature_fail} failed')

# Score all creators that have features
score_rows = fetch_all('''SELECT c.id FROM creators c
                          JOIN creator_features cf ON cf.creator_id = c.id
                          ORDER BY c.id''')
score_ok = 0
score_fail = 0
for row in score_rows:
    cid = row['id']
    try:
        score_creator(cid)
        score_ok += 1
    except Exception as e:
        score_fail += 1
        print(f'Score failed for {cid}: {e}')
print(f'Scores: {score_ok} ok, {score_fail} failed')
"
  log "Full recompute complete"
}

clean_website_links() {
  log "Cleaning creators.website (remove social links, use expanded_url when available)..."
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python scripts/rebuild_website_from_bio.py --skip-recompute
}

train_models() {
  log "Training SPS and sellability models..."
  if docker compose -f "$COMPOSE_FILE" run --rm server \
    python -c "from pipeline.sps_model import train_model as train_sps; from pipeline.sellability_model import train_model as train_sell; train_sps(); train_sell()"; then
    log "Model training complete"
  else
    warn "Model training failed — models will be retried by daily cron or manual backfill"
  fi
}

train_models_if_needed() {
  log "Checking model dimension compatibility..."
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -c "
import json, sys
from pathlib import Path
from config.settings import MODEL_META_PATH, SELLABILITY_MODEL_META_PATH
from pipeline.sps_model import FEATURE_COLS as SPS_FEATURE_COLS
from pipeline.sellability_model import FEATURE_COLS as SELLABILITY_FEATURE_COLS
from config.settings import CREATOR_TYPES

# SPS: combination scores + one-hot creator_type
# Sellability: raw features + ordinal creator_type (no one-hot)
expected_dims = {
    str(MODEL_META_PATH): len(SPS_FEATURE_COLS) + len(CREATOR_TYPES),
    str(SELLABILITY_MODEL_META_PATH): len(SELLABILITY_FEATURE_COLS),
}

needs_train = False
for meta_path, expected in expected_dims.items():
    path = Path(meta_path)
    if not path.exists():
        needs_train = True
        print(f'Meta missing: {meta_path}')
        break
    with open(path) as f:
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
"

  if [[ $? -ne 0 ]]; then
    warn "Model dimension mismatch or missing, triggering retraining..."
    train_models
  else
    log "Model files are up-to-date, skipping training"
  fi
}

run_project_sales_pipeline() {
  local summary_src="$PROJECT_DIR/汇总.xlsx"
  local summary_host="$PROJECT_DIR/data/汇总.xlsx"
  local cleaned_host="$PROJECT_DIR/data/汇总_cleaned.csv"
  local summary_container="/app/data/汇总.xlsx"
  local cleaned_container="/app/data/汇总_cleaned.csv"

  if [[ ! -f "$summary_src" ]]; then
    warn "汇总.xlsx not found at $summary_src, skipping project-level sales pipeline"
    return
  fi

  log "Running project-level sales pipeline..."
  # 将输入文件复制到 data/ 以便 docker 容器读取；data/ 在容器内为只读，所以清洗在宿主机完成
  cp -f "$summary_src" "$summary_host"

  log "  [1/5] Cleaning 汇总.xlsx ..."
  local python_cmd="python3"
  if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    python_cmd="$PROJECT_DIR/.venv/bin/python"
  fi
  "$python_cmd" "$PROJECT_DIR/scripts/clean_summary_xlsx.py" "$summary_host" "$cleaned_host"

  log "  [2/5] Importing projects ..."
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -c "
from db.connection import execute
execute('TRUNCATE TABLE projects RESTART IDENTITY CASCADE')
execute('TRUNCATE TABLE project_scores RESTART IDENTITY CASCADE')
print('Truncated projects and project_scores')
"
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python pipeline/project_import.py "$cleaned_container"

  log "  [3/5] Syncing creator profiles via Apify ..."
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python pipeline/project_creator_sync.py

  log "  [4/5] Training project-level sales model ..."
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -m pipeline.project_sps_model train

  log "  [5/5] Scoring projects ..."
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python pipeline/project_scorer.py

  log "Project-level sales pipeline complete"
}

health_check() {
  if [[ "$SKIP_HEALTHCHECK" -eq 1 ]]; then
    warn "Skip health check as requested."
    return
  fi

  log "Checking /health ..."
  for i in 1 2 3 4 5; do
    if curl -sf http://127.0.0.1/health >/dev/null 2>&1; then
      log "Health check passed."
      return
    fi
    warn "Health check attempt $i/5 failed, retry in 5s..."
    sleep 5
  done
  err "Health check failed. Check logs:"
  err "docker compose -f docker-compose.prod.yml logs --tail=200 server dashboard cron nginx"
  exit 1
}

main() {
  parse_args "$@"

  require_cmd git
  require_cmd docker
  require_cmd curl

  cd "$PROJECT_DIR"
  load_env

  if [[ "$SKIP_DB_REBUILD" -eq 1 ]]; then
    echo ""
    echo "============================================"
    echo "  CraftifyX Miner 生产更新部署"
    echo "  Release Mark: $RELEASE_MARK"
    echo "============================================"
    echo "项目目录:     $PROJECT_DIR"
    echo "目标分支:     ${BRANCH:-<当前分支>}"
    echo "操作说明:     更新代码 -> 执行迁移 -> 重启服务 -> 补算特征 -> 训练模型"
    echo "============================================"
    git_sync
    apply_migrations
    start_services
    docker compose -f "$COMPOSE_FILE" restart nginx
    backfill_features
    train_models_if_needed
    health_check
    echo ""
    log "All done."
    echo "Dashboard: http://$(hostname -I | awk '{print $1}')"
    echo "Logs:      docker compose -f docker-compose.prod.yml logs -f"
    return
  fi

  if [[ -z "$SEED_FILE" ]]; then
    if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
      err "--non-interactive requires --seed-file"
      exit 1
    fi
    read -rp "请输入种子文件路径（相对项目目录，如 data/xxx.xlsx）: " SEED_FILE
  fi
  resolve_seed_file "$SEED_FILE"
  input_admin_password_if_needed

  echo ""
  echo "============================================"
  echo "  CraftifyX Miner 生产全量重置部署"
  echo "  Release Mark: $RELEASE_MARK"
  echo "============================================"
  echo "项目目录:     $PROJECT_DIR"
  echo "目标分支:     ${BRANCH:-<当前分支>}"
  echo "种子文件:     $SEED_FILE (container: /app/$SEED_FILE)"
  echo "管理员:       $ADMIN_USERNAME"
  echo "数据库:       $(mask_db_url "$DATABASE_URL")"
  echo "操作说明:     清空 RDS -> 导种子 -> 恢复备份 -> 深度抓取 -> 清洗 website -> 补算特征/分数 -> 训练模型 -> 启服务"
  echo "============================================"

  confirm_destructive_action
  git_sync
  fix_csv_nulls_if_needed
  rebuild_database
  create_admin
  import_seeds
  import_seed_working
  resolve_restore_backup_if_needed
  restore_from_backup
  scrape_seed_working
  clean_website_links
  recompute_all_features_and_scores
  train_models
  run_project_sales_pipeline
  start_services
  docker compose -f "$COMPOSE_FILE" restart nginx
  health_check

  echo ""
  log "All done."
  echo "Dashboard: http://$(hostname -I | awk '{print $1}')"
  echo "Logs:      docker compose -f docker-compose.prod.yml logs -f"
}

main "$@"
