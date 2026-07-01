"""重新计算并修正 audience_is_nsfw / audience_is_multi_platform / has_monetization_signal。

用途：域名语义拆分后，对全量 creator_features 重新打标，不依赖原值是否为 NULL。

用法：
    python scripts/recompute_audience_and_monetization_signals.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging

from db.connection import fetch_all, get_cursor
from pipeline.feature_engine import (
    calc_audience_segment_booleans,
    calc_monetization_signal,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def recompute() -> int:
    rows = fetch_all(
        """SELECT cf.creator_id, c.bio, c.website, c.username
           FROM creator_features cf
           JOIN creators c ON c.id = cf.creator_id"""
    )
    updated = 0
    batch_size = 500

    for i, r in enumerate(rows):
        cid = r["creator_id"]
        bio = r.get("bio") or ""
        website = r.get("website") or ""
        username = r.get("username") or ""

        is_nsfw, is_multi_platform = calc_audience_segment_booleans(bio, website, username)
        has_monetization = calc_monetization_signal(bio, website)

        with get_cursor() as cur:
            cur.execute(
                """UPDATE creator_features
                      SET audience_is_nsfw = %s,
                          audience_is_multi_platform = %s,
                          has_monetization_signal = %s
                    WHERE creator_id = %s""",
                (is_nsfw, is_multi_platform, has_monetization, cid),
            )
        updated += 1

        if (i + 1) % batch_size == 0:
            logger.info("Recomputed %d / %d creators", i + 1, len(rows))

    logger.info("Recomputed %d creators in total", updated)
    return updated


if __name__ == "__main__":
    recompute()
