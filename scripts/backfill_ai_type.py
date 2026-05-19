"""对存量 ai_passed 且 creator_type_auto='unknown' 的创作者补跑 AI filter，写入类型。"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import fetch_all, get_cursor
from pipeline.ai_filter import AIFilter

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    rows = fetch_all(
        """SELECT id, bio
           FROM creators
           WHERE bd_status = 'ai_passed'
             AND creator_type_auto = 'unknown'
             AND bio IS NOT NULL AND bio != ''
           ORDER BY id"""
    )
    if not rows:
        print("没有需要补跑的创作者")
        return

    print(f"需要补跑: {len(rows)} 个创作者")

    ai_filter = AIFilter()
    batch_size = ai_filter.batch_size

    updated = 0
    failed = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        bio_batch = [{"id": r["id"], "bio": r["bio"]} for r in batch]

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(ai_filter.filter_batch(bio_batch))
        except Exception as exc:
            logger.error("Batch %d-%d failed: %s", i, i + len(batch), exc)
            failed += len(batch)
            continue
        finally:
            loop.close()

        with get_cursor() as cur:
            for r in results:
                ctype = r.get("type")
                if ctype:
                    cur.execute(
                        "UPDATE creators SET creator_type_auto = %s WHERE id = %s",
                        (ctype, r["bio_id"]),
                    )
                    updated += 1

        logger.info("Batch %d-%d done, updated %d/%d", i, i + len(batch), len(results), len(batch))

    print(f"\n完成: 更新 {updated} 个, 失败 {failed} 个")


if __name__ == "__main__":
    main()
