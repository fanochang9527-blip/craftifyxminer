#!/usr/bin/env bash
# 可选：删库重建前备份当前库（需 DATABASE_URL 与本地 psql/pg_dump）
# 用法: source .env && ./scripts/optional_pg_dump.sh
set -euo pipefail
: "${DATABASE_URL:?Set DATABASE_URL (e.g. source .env)}"
OUT="${1:-./backup_$(date +%Y%m%d_%H%M%S).dump}"
echo "Writing custom-format dump to $OUT"
pg_dump "$DATABASE_URL" -Fc -f "$OUT"
echo "Done."
