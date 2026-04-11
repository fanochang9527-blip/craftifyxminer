"""创作者类型自动分类器。

基于 bio_rules.yaml 的 type_tags + 推文内容关键词，
为每个创作者预测六种类型之一，结果写入 creators.creator_type_auto。

优先级：bio type_tags 精确匹配 > 推文内容关键词 > 无匹配则返回 'unknown'
"""

import logging

from config.settings import CREATOR_TYPES
from db.connection import fetch_all, get_cursor
from pipeline.bio_rule_filter import BioRuleFilter

logger = logging.getLogger(__name__)

TWEET_TYPE_KEYWORDS: dict[str, list[str]] = {
    "oc_creator": ["my oc", "original character", "#oc", "#myoc", "oc art"],
    "vtuber": ["#vtuber", "virtual youtuber", "live2d", "debut stream"],
    "fan_artist": ["#fanart", "doujin", "fan art", "#二次創作"],
    "game_creator": ["#gamedev", "#indiedev", "indie game", "devlog"],
    "content_creator": ["#arttips", "#tutorial", "speed paint", "art process"],
}


def classify_creator(bio: str, website: str = "", tweets_text: str = "") -> str:
    """Return one of CREATOR_TYPES for a single creator."""
    bf = BioRuleFilter()
    result = bf.filter(bio, website)
    if result["type"] and result["type"] in CREATOR_TYPES:
        return result["type"]

    text_lower = tweets_text.lower()
    hits: dict[str, int] = {}
    for ctype, keywords in TWEET_TYPE_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > 0:
            hits[ctype] = count

    if hits:
        return max(hits, key=hits.get)  # type: ignore[arg-type]

    return "unknown"


def classify_all_pending(batch_size: int = 500) -> int:
    """Classify creators that don't have creator_type_auto yet.

    Returns number of creators classified.
    """
    pending = fetch_all(
        """SELECT c.id, c.bio, c.website,
                  COALESCE(
                      (SELECT string_agg(s.text, ' ')
                       FROM (
                           SELECT t.text
                           FROM tweets t
                           WHERE t.creator_id = c.id
                           ORDER BY t.created_at DESC
                           LIMIT 20
                       ) s),
                      ''
                  ) AS tweets_text
           FROM creators c
           WHERE c.creator_type_auto IS NULL
             AND (c.bio IS NOT NULL AND c.bio != '')
           LIMIT %s""",
        (batch_size,),
    )

    if not pending:
        logger.info("No pending creators to classify")
        return 0

    classified = 0
    with get_cursor() as cur:
        for row in pending:
            ctype = classify_creator(
                bio=row["bio"] or "",
                website=row.get("website") or "",
                tweets_text=row.get("tweets_text") or "",
            )
            cur.execute(
                "UPDATE creators SET creator_type_auto = %s WHERE id = %s",
                (ctype, row["id"]),
            )
            classified += 1

    logger.info("Classified %d creators", classified)
    return classified
