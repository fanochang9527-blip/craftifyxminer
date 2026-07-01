"""回 fill 可卖货模型新增特征。

对已有 creator_features 记录补算：
- audience_is_nsfw / audience_is_multi_platform
- has_monetization_signal
- mention_rate / retweet_rate

用法：
    python scripts/backfill_sellability_new_features.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging

from db.connection import fetch_all, get_cursor
from pipeline.feature_engine import (
    calc_audience_segment_booleans,
    calc_mention_rate,
    calc_monetization_signal,
    calc_retweet_rate,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def backfill() -> int:
    rows = fetch_all(
        """SELECT cf.creator_id, c.bio, c.website, c.username
           FROM creator_features cf
           JOIN creators c ON c.id = cf.creator_id
           WHERE cf.audience_is_nsfw IS NULL
              OR cf.audience_is_multi_platform IS NULL
              OR cf.has_monetization_signal IS NULL
              OR cf.mention_rate IS NULL
              OR cf.retweet_rate IS NULL"""
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

        tweets = fetch_all(
            "SELECT text, retweets FROM tweets WHERE creator_id = %s", (cid,)
        )
        mention_rate = calc_mention_rate(tweets)
        retweet_rate = calc_retweet_rate(tweets)

        with get_cursor() as cur:
            cur.execute(
                """UPDATE creator_features
                      SET audience_is_nsfw = %s,
                          audience_is_multi_platform = %s,
                          has_monetization_signal = %s,
                          mention_rate = %s,
                          retweet_rate = %s
                    WHERE creator_id = %s""",
                (is_nsfw, is_multi_platform, has_monetization, mention_rate, retweet_rate, cid),
            )
        updated += 1

        if (i + 1) % batch_size == 0:
            logger.info("Backfilled %d / %d creators", i + 1, len(rows))

    logger.info("Backfilled %d creators in total", updated)
    return updated


if __name__ == "__main__":
    backfill()
