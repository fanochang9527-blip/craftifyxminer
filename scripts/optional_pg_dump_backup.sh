#!/usr/bin/env bash
# 可选：删库重建前备份当前库（自定义/自定义格式）
# 用法: cd 项目根目录 && set -a && source .env && set +a && bash scripts/optional_pg_dump_backup.sh [输出文件.dump]
set -euo pipefail
: "${DATABASE_URL:?请先 export DATABASE_URL 或 source .env}"
OUT="${1:-backup_$(date +%Y%m%d_%H%M%S).dump}"
pg_dump "$DATABASE_URL" -Fc -f "$OUT"
echo "备份已写入: $OUT"
