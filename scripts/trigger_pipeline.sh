#!/usr/bin/env bash
#
# 手动触发完整流水线（生产环境）
# 用法:
#   cd /opt/craftifyxminer
#   bash scripts/trigger_pipeline.sh                    # 默认参数
#   bash scripts/trigger_pipeline.sh --deep-limit 10    # 限制深度抓取 10 人
#   bash scripts/trigger_pipeline.sh --smoke            # 冒烟模式（1 锚点，40 following，3 深度）
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# 加载 .env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# 默认参数
ANCHORS=""
MAX_FOLLOWING=""
DEEP_LIMIT=""
SMOKE=0

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --anchors)
            ANCHORS="$2"
            shift 2
            ;;
        --max-following)
            MAX_FOLLOWING="$2"
            shift 2
            ;;
        --deep-limit)
            DEEP_LIMIT="$2"
            shift 2
            ;;
        --smoke)
            SMOKE=1
            shift
            ;;
        -h|--help)
            echo "用法: bash scripts/trigger_pipeline.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --anchors N         种子锚点数量（默认：全部种子）"
            echo "  --max-following N   每个锚点最大 Following 数（默认：500）"
            echo "  --deep-limit N      深度抓取人数上限（默认：50）"
            echo "  --smoke             冒烟模式（1 锚点，40 following，3 深度）"
            echo "  -h, --help          显示帮助"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            echo "使用 --help 查看用法"
            exit 1
            ;;
    esac
done

# 构建 Python 参数字符串
PY_ARGS=""
if [ -n "$DEEP_LIMIT" ]; then
    PY_ARGS="$PY_ARGS, deep_limit=$DEEP_LIMIT"
fi

if [ "$SMOKE" -eq 1 ]; then
    echo "========================================"
    echo "  冒烟模式: 1 锚点, 40 following, 3 深度"
    echo "========================================"
    docker compose -f docker-compose.prod.yml run --rm server \
        python -c "
import sys
sys.path.insert(0, '/app')
from db.connection import fetch_all
from pipeline.runner import run_full_pipeline

seeds = fetch_all('SELECT id, username FROM creators WHERE is_seed=true ORDER BY id LIMIT 1')
anchors = [{'username': s['username'], 'strategy': 'smoke', 'seed_id': s['id']} for s in seeds]
result = run_full_pipeline(anchors=anchors, deep_limit=3)
print(result)
"
else
    echo "========================================"
    echo "  完整流水线触发"
    echo "========================================"
    
    # 构建 anchors 参数
    if [ -n "$ANCHORS" ]; then
        docker compose -f docker-compose.prod.yml run --rm server \
            python -c "
import sys
sys.path.insert(0, '/app')
from db.connection import fetch_all
from pipeline.runner import run_full_pipeline

seeds = fetch_all('SELECT id, username FROM creators WHERE is_seed=true ORDER BY id LIMIT $ANCHORS')
anchors = [{'username': s['username'], 'strategy': 'seed_following', 'seed_id': s['id']} for s in seeds]
result = run_full_pipeline(anchors=anchors${PY_ARGS})
print(result)
"
    else
        # 使用全部种子
        docker compose -f docker-compose.prod.yml run --rm server \
            python -c "
import sys
sys.path.insert(0, '/app')
from pipeline.runner import run_full_pipeline
result = run_full_pipeline(${PY_ARGS#, })
print(result)
"
    fi
fi

echo ""
echo "========================================"
echo "  流水线执行完毕"
echo "========================================"
