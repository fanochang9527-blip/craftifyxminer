#!/bin/bash
# 多模态内容风格补算守护脚本
# 当 Python 脚本因异常退出时自动重启，直到所有数据处理完毕

set -euo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/backfill_content_style_daemon_$(date +%Y%m%d_%H%M%S).log"
RESTART_COUNT=0
MAX_RESTARTS=100

# 渐进式退避：首次 60s，每次 +30s，封顶 300s（5分钟）
wait_time() {
    local wt=$((60 + RESTART_COUNT * 30))
    if [ "$wt" -gt 300 ]; then
        wt=300
    fi
    echo "$wt"
}

while [ $RESTART_COUNT -lt $MAX_RESTARTS ]; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Starting backfill_content_style.py (attempt $((RESTART_COUNT + 1))/${MAX_RESTARTS}) ===" | tee -a "$LOG_FILE"

    set +e
    python scripts/backfill_content_style.py --limit 500 --max-rounds 100 >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?
    set -e

    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Script completed successfully. Exiting daemon. ===" | tee -a "$LOG_FILE"
        break
    fi

    RESTART_COUNT=$((RESTART_COUNT + 1))
    WT=$(wait_time)

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Script exited with code $EXIT_CODE. Restarting in ${WT}s... (restart $RESTART_COUNT/${MAX_RESTARTS}) ===" | tee -a "$LOG_FILE"
    sleep "$WT"
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Daemon finished. Total restarts: $RESTART_COUNT ===" | tee -a "$LOG_FILE"
