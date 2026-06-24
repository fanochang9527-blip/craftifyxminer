"""项目级评分：为 projects 表中的项目生成预测销量并写入 project_scores。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.connection import fetch_all, get_cursor
from pipeline.project_sps_model import predict_batch, predict_sales_batch

logger = logging.getLogger(__name__)


CREATOR_FEATURE_COLS = [
    "creator_followers_log",
    "creator_following_follower_ratio",
    "creator_avg_daily_posts_30d",
    "creator_reply_engagement_rate",
    "creator_account_age_days_log",
    "creator_has_shop_link",
    "creator_is_nsfw",
    "creator_is_multi_platform",
    "creator_market_tier_high",
    "creator_market_tier_mid",
    "creator_market_tier_low",
    "creator_content_furry",
    "creator_content_anime",
    "creator_content_vtuber",
    "creator_content_gaming",
    "creator_content_webcomic",
    "creator_content_bl",
    "creator_content_gl",
    "creator_content_nsfw",
]


def _load_pending_projects() -> list[dict]:
    """加载所有待评分的项目（已补齐创作者特征）。"""
    feature_cols = ", ".join(CREATOR_FEATURE_COLS)
    return (
        fetch_all(
            f"""
            SELECT project_id, creator_id,
                   domain, product_attribute, price,
                   {feature_cols}
            FROM projects
            WHERE creator_username IS NOT NULL
            """
        )
        or []
    )


def score_projects() -> dict:
    """为所有项目生成预测销量并写入 project_scores。

    Returns:
        {"scored": int, "skipped": int}
    """
    rows = _load_pending_projects()
    if not rows:
        logger.info("No projects to score")
        return {"scored": 0, "skipped": 0}

    sales_batch = predict_sales_batch(rows)
    sps_batch = predict_batch(rows)

    scored = skipped = 0
    with get_cursor() as cur:
        for row, predicted_sales, sps_score in zip(rows, sales_batch, sps_batch):
            if predicted_sales is None or sps_score is None:
                skipped += 1
                continue

            contact_probability = round(min(max(sps_score / 100.0, 0.0), 1.0), 4)

            cur.execute(
                """
                INSERT INTO project_scores
                    (project_id, creator_id, predicted_sales, sps_score,
                     confidence, contact_probability, predicted_response_rate)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id) DO UPDATE SET
                    creator_id = EXCLUDED.creator_id,
                    predicted_sales = EXCLUDED.predicted_sales,
                    sps_score = EXCLUDED.sps_score,
                    confidence = EXCLUDED.confidence,
                    contact_probability = EXCLUDED.contact_probability,
                    predicted_response_rate = EXCLUDED.predicted_response_rate,
                    updated_at = NOW()
                """,
                (
                    row["project_id"],
                    row["creator_id"],
                    predicted_sales,
                    sps_score,
                    0.0,
                    contact_probability,
                    contact_probability,
                ),
            )
            scored += 1

    logger.info("Project scoring complete: scored=%d, skipped=%d", scored, skipped)
    return {"scored": scored, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = score_projects()
    print(f"Scored {result['scored']} projects, skipped {result['skipped']}")
