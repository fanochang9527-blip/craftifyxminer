"""一次性回填：将现有 creators 的当前 followers 写入 snapshot 表作为初始点。"""

import sys
from pathlib import Path

# 将项目根目录加入模块搜索路径（支持从 scripts/ 目录直接运行）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
from datetime import datetime

from db.connection import fetch_all, get_cursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def backfill_all() -> dict:
    rows = fetch_all(
        "SELECT id, followers, following, tweets_count, is_seed, first_seen_at FROM creators WHERE followers > 0"
    )
    inserted = 0
    for r in rows:
        table = "seed_follower_snapshots" if r["is_seed"] else "creator_snapshots"
        observed = r["first_seen_at"] or datetime.now()
        with get_cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {table} (creator_id, observed_at, followers, following, tweets_count, source)
                VALUES (%s, DATE_TRUNC('day', %s), %s, %s, %s, 'backfill')
                ON CONFLICT (creator_id, observed_at) DO NOTHING
                """,
                (r["id"], observed, r["followers"], r["following"], r["tweets_count"]),
            )
            inserted += 1
    logger.info("Backfilled %d snapshots", inserted)
    return {"inserted": inserted}


if __name__ == "__main__":
    backfill_all()
