#!/usr/bin/env python3
"""将临时 PostgreSQL 数据库中的数据按表导入当前 RDS。

用法：
    TEMP_DB_URL="postgresql://postgres:temp123@127.0.0.1:5434/temp_backup" \
    .venv/bin/python scripts/restore_all_tables_from_temp_db.py

逻辑：
1. 连接临时数据库（完整备份）和当前 RDS
2. 按依赖顺序逐个表导入
3. 只导入目标 RDS 中存在的列（兼容 schema 差异）
4. 目标表先 TRUNCATE，再 INSERT
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import psycopg2
import psycopg2.extras

TEMP_DB_URL = os.environ.get("TEMP_DB_URL", "postgresql://postgres:temp123@127.0.0.1:5434/temp_backup")
TARGET_DB_URL = os.environ["DATABASE_URL"]

# 按外键依赖顺序排列（被引用的表在前）
TABLES = [
    "users",
    "creators",
    "creators_detail",
    "creator_raw_profiles",
    "tweets",
    "creator_features",
    "creator_scores",
    "creator_content_analysis",
    "creator_graph",
    "creator_snapshots",
    "bd_decisions",
    "cost_tracking",
    "discovery_batches",
    "model_evaluations",
    "projects",
    "project_scores",
    "processed_datasets",
    "outreach_log",
    "sales_feedback",
    "follower_alerts",
    "login_attempts",
    "seed_follower_snapshots",
    "seed_growth_alerts",
]


def get_conn(url: str):
    return psycopg2.connect(url)


def get_columns(cur, table: str, schema: str = "public") -> list[str]:
    cur.execute(
        """SELECT column_name
           FROM information_schema.columns
           WHERE table_schema = %s AND table_name = %s
           ORDER BY ordinal_position""",
        (schema, table),
    )
    return [r[0] for r in cur.fetchall()]


def _adapt_value(value):
    """适配 Python dict 到 PostgreSQL json/jsonb；list 保持原样用于 array 列。"""
    if isinstance(value, dict):
        return psycopg2.extras.Json(value)
    return value


def copy_table(src_cur, dst_cur, table: str, columns: list[str]) -> int:
    if not columns:
        return 0
    cols_sql = ", ".join(f'"{c}"' for c in columns)
    src_cur.execute(f"SELECT {cols_sql} FROM {table}")
    rows = src_cur.fetchall()
    if not rows:
        return 0

    dst_cur.execute(f"TRUNCATE TABLE {table} CASCADE")
    placeholders = ", ".join(["%s"] * len(columns))
    adapted_rows = [[_adapt_value(v) for v in row] for row in rows]
    dst_cur.executemany(
        f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders})",
        adapted_rows,
    )
    return len(rows)


def main() -> int:
    print(f"Connecting to temp DB: {TEMP_DB_URL.replace('temp123', '***')}")
    src_conn = get_conn(TEMP_DB_URL)
    dst_conn = get_conn(TARGET_DB_URL)

    src_cur = src_conn.cursor()
    dst_cur = dst_conn.cursor()

    for table in TABLES:
        src_cols = get_columns(src_cur, table, "public")
        dst_cols = get_columns(dst_cur, table, "public")
        common_cols = [c for c in src_cols if c in dst_cols]
        skipped_cols = [c for c in src_cols if c not in dst_cols]

        print(f"\nTable: {table}")
        print(f"  source cols: {len(src_cols)}, target cols: {len(dst_cols)}, common: {len(common_cols)}")
        if skipped_cols:
            print(f"  skipped cols (not in target): {skipped_cols}")

        try:
            count = copy_table(src_cur, dst_cur, table, common_cols)
            dst_conn.commit()
            print(f"  imported: {count} rows")
        except Exception as e:
            dst_conn.rollback()
            print(f"  ERROR: {e}")
            # 继续下一张表，不中断

    src_cur.close()
    dst_cur.close()
    src_conn.close()
    dst_conn.close()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
