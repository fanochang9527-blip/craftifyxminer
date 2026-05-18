#!/usr/bin/env bash
#
# CraftifyX Miner — 一键部署脚本
# 适用系统: Ubuntu 20/22, CentOS 7/8 (自动检测)
# 用法: sudo bash scripts/deploy.sh
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
ENV_FILE="$PROJECT_DIR/.env"

# ──────────────────────────────────────────────
# 1. OS 检测
# ──────────────────────────────────────────────
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_ID="$ID"
        OS_VERSION="${VERSION_ID%%.*}"
    else
        err "Cannot detect OS. Supported: Ubuntu 20/22, CentOS 7/8"
        exit 1
    fi
    log "Detected OS: $ID $VERSION_ID"
}

# ──────────────────────────────────────────────
# 2. 安装 Docker + Compose
# ──────────────────────────────────────────────
install_docker() {
    if command -v docker &>/dev/null; then
        log "Docker already installed: $(docker --version)"
    else
        log "Installing Docker..."
        if [ "$OS_ID" = "ubuntu" ] || [ "$OS_ID" = "debian" ]; then
            apt-get update -qq
            apt-get install -y -qq ca-certificates curl gnupg lsb-release
            install -m 0755 -d /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/$OS_ID/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
            chmod a+r /etc/apt/keyrings/docker.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$OS_ID $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
            apt-get update -qq
            apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
        elif [ "$OS_ID" = "centos" ] || [ "$OS_ID" = "rhel" ]; then
            yum install -y yum-utils
            yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
            yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
            systemctl start docker
            systemctl enable docker
        fi
        log "Docker installed: $(docker --version)"
    fi

    if ! docker compose version &>/dev/null; then
        err "docker compose plugin not found"
        exit 1
    fi
    log "Docker Compose: $(docker compose version --short)"
}

# ──────────────────────────────────────────────
# 3. 交互式 .env 配置
# ──────────────────────────────────────────────
configure_env() {
    if [ -f "$ENV_FILE" ]; then
        warn ".env already exists. Overwrite? [y/N]"
        read -r ans
        if [ "$ans" != "y" ] && [ "$ans" != "Y" ]; then
            log "Keeping existing .env"
            return
        fi
    fi

    log "Configuring .env — press Enter to accept defaults"
    echo ""

    read -rp "DATABASE_URL [postgresql://miner:password@rds-host:5432/craftifyx_miner]: " DB_URL
    DB_URL="${DB_URL:-postgresql://miner:password@localhost:5432/craftifyx_miner}"

    read -rp "APIFY_API_TOKEN: " APIFY_TOKEN
    read -rp "APIFY_WEBHOOK_SECRET: " APIFY_WH_SECRET

    read -rp "LLM_PROVIDER [moonshot]: " LLM_PROV
    LLM_PROV="${LLM_PROV:-moonshot}"

    read -rp "MOONSHOT_API_KEY: " MS_KEY
    read -rp "MOONSHOT_BASE_URL [https://api.moonshot.ai/v1]: " MS_URL
    MS_URL="${MS_URL:-https://api.moonshot.ai/v1}"

    read -rp "DEEPSEEK_API_KEY (可选，回车跳过): " DS2_KEY
    read -rp "DASHSCOPE_API_KEY (可选，回车跳过): " DS_KEY

    read -rp "NGINX_SERVER_NAME [_]: " NGINX_NAME
    NGINX_NAME="${NGINX_NAME:-_}"

    read -rp "ADMIN_USERNAME [admin]: " ADMIN_USER
    ADMIN_USER="${ADMIN_USER:-admin}"

    read -rsp "ADMIN_PASSWORD (min 8 chars, letters+digits): " ADMIN_PASS
    echo ""
    if [ -z "$ADMIN_PASS" ]; then
        ADMIN_PASS="Admin$(openssl rand -hex 4)"
        warn "Generated admin password: $ADMIN_PASS"
    fi

    FLASK_KEY=$(openssl rand -hex 32)
    JWT_KEY=$(openssl rand -hex 32)

    cat > "$ENV_FILE" << EOF
# --- Database ---
DATABASE_URL=$DB_URL
POSTGRES_DB=craftifyx_miner
POSTGRES_USER=miner

# --- Apify ---
APIFY_API_TOKEN=$APIFY_TOKEN
APIFY_WEBHOOK_SECRET=$APIFY_WH_SECRET

# --- LLM ---
LLM_PROVIDER=$LLM_PROV
LLM_TIMEOUT=120
LLM_FALLBACK_CHAIN=moonshot,deepseek,dashscope
MOONSHOT_API_KEY=$MS_KEY
MOONSHOT_BASE_URL=$MS_URL
DEEPSEEK_API_KEY=$DS2_KEY
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DASHSCOPE_API_KEY=$DS_KEY

# --- Flask & Auth ---
FLASK_SECRET_KEY=$FLASK_KEY
JWT_SECRET_KEY=$JWT_KEY
FLASK_PORT=5000

# --- Scaling ---
DAILY_ANCHOR_COUNT=20
MAX_FOLLOWING_PER_ANCHOR=500
DEEP_SCRAPE_BATCH_SIZE=50

# --- Budget ---
MONTHLY_BUDGET_USD=500
DAILY_APIFY_BUDGET_USD=20
MONTHLY_LLM_BUDGET_USD=10

# --- Backup ---
BACKUP_RETENTION_DAYS=7
EOF

    log ".env written"
}

# ──────────────────────────────────────────────
# 4. 初始化数据库 Schema
# ──────────────────────────────────────────────
init_database() {
    log "Initializing database schema..."
    source "$ENV_FILE"

    if command -v psql &>/dev/null; then
        psql "$DATABASE_URL" -f "$PROJECT_DIR/db/schema.sql"
        psql "$DATABASE_URL" -f "$PROJECT_DIR/db/indexes.sql" 2>/dev/null || true
        psql "$DATABASE_URL" -f "$PROJECT_DIR/db/migrations/004_sps_ml_refactor.sql" 2>/dev/null || true
        psql "$DATABASE_URL" -f "$PROJECT_DIR/db/migrations/005_seed_platform_account_unique.sql" 2>/dev/null || true
        psql "$DATABASE_URL" -f "$PROJECT_DIR/db/migrations/006_dual_model_scores.sql" 2>/dev/null || true
    else
        warn "psql not found locally, running via Docker..."
        docker run --rm \
            -v "$PROJECT_DIR/db:/sql:ro" \
            --network host \
            postgres:18-alpine \
            sh -c "psql '$DATABASE_URL' -f /sql/schema.sql && psql '$DATABASE_URL' -f /sql/indexes.sql 2>/dev/null || true && psql '$DATABASE_URL' -f /sql/migrations/004_sps_ml_refactor.sql 2>/dev/null || true && psql '$DATABASE_URL' -f /sql/migrations/005_seed_platform_account_unique.sql 2>/dev/null || true && psql '$DATABASE_URL' -f /sql/migrations/006_dual_model_scores.sql 2>/dev/null || true"
    fi
    log "Database schema initialized"
}

# ──────────────────────────────────────────────
# 5. 创建 Admin 用户
# ──────────────────────────────────────────────
create_admin() {
    log "Creating admin user..."
    source "$ENV_FILE"

    docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" build --quiet server

    docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" run --rm \
        server python -m auth.manage create-admin \
        --username "${ADMIN_USER:-admin}" \
        --password "${ADMIN_PASS:-Admin123}"

    log "Admin user created"
}

# ──────────────────────────────────────────────
# 6. 启动服务
# ──────────────────────────────────────────────
start_services() {
    log "Building and starting services..."
    cd "$PROJECT_DIR"
    docker compose -f docker-compose.prod.yml up -d --build
    log "Services started"
}

# ──────────────────────────────────────────────
# 6.5 特征工程补算（有 tweets 但无 creator_features 的创作者）
# ──────────────────────────────────────────────
backfill_features() {
    log "Backfilling missing creator features..."
    docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" run --rm server \
        python -c "from pipeline.feature_engine import backfill_missing_features; backfill_missing_features()"
    log "Feature backfill complete"
}

# ──────────────────────────────────────────────
# 6.6 冷启动模型训练（文件不存在时才执行）
# ──────────────────────────────────────────────
train_models_if_missing() {
    local model_dir="$PROJECT_DIR/models"
    if [[ -f "$model_dir/sps_model.joblib" && -f "$model_dir/sellability_model.joblib" ]]; then
        log "Model files already exist, skipping cold-start training"
        return
    fi
    warn "Model files missing, triggering cold-start training..."
    docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" run --rm server \
        python -c "from pipeline.runner import train_models; train_models()"
    log "Cold-start training complete"
}

# ──────────────────────────────────────────────
# 7. 配置备份 Crontab
# ──────────────────────────────────────────────
setup_backup() {
    CRON_CMD="0 3 * * * $PROJECT_DIR/scripts/backup_db.sh >> $PROJECT_DIR/logs/backup.log 2>&1"
    if crontab -l 2>/dev/null | grep -q "backup_db.sh"; then
        log "Backup cron already configured"
    else
        (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
        log "Backup cron job added (daily 3:00 AM)"
    fi
}

# ──────────────────────────────────────────────
# 8. 防火墙
# ──────────────────────────────────────────────
configure_firewall() {
    if command -v ufw &>/dev/null; then
        ufw allow 22/tcp
        ufw allow 80/tcp
        ufw allow 443/tcp
        ufw --force enable
        log "UFW configured (22, 80, 443)"
    elif command -v firewall-cmd &>/dev/null; then
        firewall-cmd --permanent --add-service=ssh
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --reload
        log "firewalld configured (22, 80, 443)"
    else
        warn "No firewall utility found — please configure manually"
    fi
}

# ──────────────────────────────────────────────
# 9. 健康检查
# ──────────────────────────────────────────────
verify_health() {
    log "Waiting for services to be ready..."
    sleep 10

    for i in 1 2 3 4 5; do
        if curl -sf http://localhost/health > /dev/null 2>&1; then
            log "Health check passed!"
            return
        fi
        warn "Attempt $i/5 failed, retrying in 5s..."
        sleep 5
    done
    err "Health check failed after 5 attempts. Check logs: docker compose -f docker-compose.prod.yml logs"
}

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
main() {
    echo "============================================"
    echo "  CraftifyX Miner — Production Deployment"
    echo "============================================"
    echo ""

    detect_os
    install_docker
    configure_env
    init_database
    create_admin
    start_services
    docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" restart nginx
    backfill_features
    train_models_if_missing
    setup_backup
    configure_firewall
    verify_health

    echo ""
    echo "============================================"
    log "Deployment complete!"
    echo ""
    echo "  Dashboard:  http://$(hostname -I | awk '{print $1}')"
    echo "  Health:     http://$(hostname -I | awk '{print $1}')/health"
    echo ""
    echo "  Admin user: ${ADMIN_USER:-admin}"
    if [ -n "${ADMIN_PASS:-}" ]; then
        echo "  Admin pass: $ADMIN_PASS"
    fi
    echo ""
    echo "  Logs:       docker compose -f docker-compose.prod.yml logs -f"
    echo "  Stop:       docker compose -f docker-compose.prod.yml down"
    echo "============================================"
}

main "$@"
