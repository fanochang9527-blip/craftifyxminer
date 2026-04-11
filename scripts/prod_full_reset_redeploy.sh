#!/usr/bin/env bash
#
# 生产全量重置部署（ECS + RDS）
# 发布标记：20260411
# 适用场景：确认清空 RDS 旧数据并按最新代码全量重建、导入新种子、重启服务。
#
# 用法示例（交互）:
#   cd /opt/craftifyxminer
#   bash scripts/prod_full_reset_redeploy.sh --branch main --seed-file data/创作者账号链接及销量收集.xlsx
#
# 用法示例（非交互）:
#   bash scripts/prod_full_reset_redeploy.sh \
#     --non-interactive \
#     --branch main \
#     --seed-file data/creators_seed_from_xlsx.csv \
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
ADMIN_USERNAME="admin"
ADMIN_PASSWORD=""
NON_INTERACTIVE=0
SKIP_GIT_PULL=0
SKIP_HEALTHCHECK=0
RELEASE_MARK="20260411"

usage() {
  cat <<'EOF'
生产全量重置部署脚本（会清空 RDS public schema）
发布标记: 20260411

参数:
  --branch <name>            Git 分支名（默认当前分支）
  --seed-file <path>         种子文件路径（必须在项目 data/ 下，支持 .xlsx/.csv）
  --admin-username <name>    管理员用户名（默认 admin）
  --admin-password <pwd>     管理员密码（不传则交互输入）
  --non-interactive          非交互模式（必须提供 --seed-file 与 --admin-password）
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
  if [[ "$abs" != "$data_prefix"* ]]; then
    err "Seed file must be inside project data/: $PROJECT_DIR/data/"
    exit 1
  fi

  local rel="${abs#"$PROJECT_DIR/"}"
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
  log "Creating admin user: $ADMIN_USERNAME"
  docker compose -f "$COMPOSE_FILE" run --rm server \
    python -m auth.manage create-admin \
    --username "$ADMIN_USERNAME" \
    --password "$ADMIN_PASSWORD"
}

import_seeds() {
  local ext="${SEED_FILE##*.}"
  local container_path="/app/${SEED_FILE}"

  case "$ext" in
    xlsx|XLSX)
      log "Importing seed xlsx: $container_path"
      docker compose -f "$COMPOSE_FILE" run --rm server \
        python -m pipeline.seed_import \
        --xlsx "$container_path" \
        --skip-post-pipeline
      ;;
    csv|CSV)
      log "Importing seed csv: $container_path"
      docker compose -f "$COMPOSE_FILE" run --rm server \
        python -m pipeline.seed_import \
        --csv "$container_path" \
        --skip-post-pipeline
      ;;
    *)
      err "Unsupported seed file extension: .$ext (use .xlsx or .csv)"
      exit 1
      ;;
  esac
}

start_services() {
  log "Starting services with rebuild..."
  docker compose -f "$COMPOSE_FILE" up -d --build
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
  echo "操作说明:     清空 RDS public schema -> 重建 -> 导种子 -> 启服务"
  echo "============================================"

  confirm_destructive_action
  git_sync
  rebuild_database
  create_admin
  import_seeds
  start_services
  health_check

  echo ""
  log "All done."
  echo "Dashboard: http://$(hostname -I | awk '{print $1}')"
  echo "Logs:      docker compose -f docker-compose.prod.yml logs -f"
}

main "$@"
