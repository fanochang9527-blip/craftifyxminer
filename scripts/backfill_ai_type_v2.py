"""对存量 ai_passed 且 creator_type_auto='unknown' 的创作者补跑 AI filter，写入类型。

v2 改进:
- batch_size 提升到 50，减少 API 调用次数
- 支持断点续传（每次只查询尚未处理的）
- 每批完成后立即提交，避免长时间事务
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import fetch_all, get_cursor
from pipeline.ai_filter import AIFilter

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BATCH_SIZE = 50


def get_pending_count() -> int:
    row = fetch_all(
        "SELECT COUNT(*) AS cnt FROM creators WHERE bd_status = 'ai_passed' AND creator_type_auto = 'unknown' AND bio IS NOT NULL AND bio != ''"
    )
    return row[0]["cnt"] if row else 0


def get_pending_batch(batch_size: int) -> list[dict]:
    """Fetch next batch of pending creators."""
    rows = fetch_all(
        """SELECT id, bio
           FROM creators
           WHERE bd_status = 'ai_passed'
             AND creator_type_auto = 'unknown'
             AND bio IS NOT NULL AND bio != ''
           ORDER BY id
           LIMIT %s""",
        (batch_size,),
    )
    return rows


def main():
    total_pending = get_pending_count()
    if not total_pending:
        print("没有需要补跑的创作者")
        return

    print(f"需要补跑: {total_pending} 个创作者 (batch_size={BATCH_SIZE})")

    ai_filter = AIFilter(batch_size=BATCH_SIZE)

    total_updated = 0
    total_failed = 0
    batch_num = 0

    while True:
        rows = get_pending_batch(BATCH_SIZE)
        if not rows:
            break

        batch_num += 1
        bio_batch = [{"id": r["id"], "bio": r["bio"]} for r in rows]
        n = len(bio_batch)

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(ai_filter.filter_batch(bio_batch))
        except Exception as exc:
            logger.error("Batch %d (%d items) failed: %s", batch_num, n, exc)
            total_failed += n
            continue
        finally:
            loop.close()

        updated = 0
        with get_cursor() as cur:
            for r in results:
                ctype = r.get("type")
                if ctype:
                    cur.execute(
                        "UPDATE creators SET creator_type_auto = %s WHERE id = %s",
                        (ctype, r["bio_id"]),
                    )
                    updated += 1

        total_updated += updated
        remaining = get_pending_count()
        logger.info(
            "Batch %d done: updated %d/%d, total_updated=%d, remaining=%d",
            batch_num, updated, n, total_updated, remaining,
        )

        if remaining == 0:
            break

    print(f"\n完成: 更新 {total_updated} 个, 失败 {total_failed} 个")


if __name__ == "__main__":
    main()
