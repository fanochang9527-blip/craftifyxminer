"""Backfill DNA features from existing data (no API calls).

为已有种子/interested 创作者，基于现有 tweets + bio + profile 计算 DNA 数值特征，
写入 creator_features，并训练 DNA Lasso 模型。形象标签默认 mixed（待 LLM 分析后覆盖）。

Usage:
    .venv/bin/python scripts/backfill_dna_features.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import fetch_all, fetch_one, get_cursor
from pipeline.creator_dna import (
    _compute_raw_features,
    _determine_market_tier,
    _extract_multi_platform,
    _extract_nsfw,
    _extract_shop_signals,
)
from pipeline.sps_model import train_model_dna

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def backfill_one(creator_id: int) -> bool:
    """Compute rule-based DNA features for one creator and write to creator_features."""
    creator = fetch_one("SELECT * FROM creators WHERE id = %s", (creator_id,))
    if not creator:
        return False

    detail = fetch_one("SELECT * FROM creators_detail WHERE creator_id = %s", (creator_id,))
    tweets = fetch_all(
        "SELECT * FROM tweets WHERE creator_id = %s ORDER BY created_at DESC",
        (creator_id,),
    )

    bio = creator.get("bio") or ""
    website = creator.get("website") or ""
    username = creator.get("username") or ""
    website_links = detail.get("website_links") if detail else None

    raw_features = _compute_raw_features(creator, tweets)
    has_shop_link, _ = _extract_shop_signals(bio, website, website_links)
    is_nsfw = _extract_nsfw(bio, username, tweets)
    is_multi_platform = _extract_multi_platform(bio, website)

    country = (detail.get("country") if detail else None) or creator.get("country")
    region = (detail.get("region") if detail else None) or creator.get("region")
    location = (detail.get("location") if detail else None) or creator.get("location")
    display_name = creator.get("display_name") or creator.get("username") or ""
    market_tier = _determine_market_tier(country, region, location, bio, display_name)

    # 未做 LLM 的默认 anime；nsfw 从规则推断
    features = {
        "creator_id": creator_id,
        "followers_log": raw_features["followers_log"],
        "following_follower_ratio": raw_features["following_follower_ratio"],
        "avg_daily_posts_30d": raw_features["avg_daily_posts_30d"],
        "reply_engagement_rate": raw_features["reply_engagement_rate"],
        "account_age_days_log": raw_features["account_age_days_log"],
        "has_shop_link": 1.0 if has_shop_link else 0.0,
        "is_nsfw": 1.0 if is_nsfw else 0.0,
        "is_multi_platform": 1.0 if is_multi_platform else 0.0,
        "market_tier_high": 1.0 if market_tier == "high" else 0.0,
        "market_tier_mid": 1.0 if market_tier == "mid" else 0.0,
        "market_tier_low": 1.0 if market_tier == "low" else 0.0,
        "content_furry": 0.0,
        "content_anime": 1.0,
        "content_vtuber": 0.0,
        "content_gaming": 0.0,
        "content_webcomic": 0.0,
        "content_bl": 0.0,
        "content_gl": 0.0,
        "content_nsfw": 1.0 if is_nsfw else 0.0,
    }

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO creator_features (
                   creator_id, followers_log, following_follower_ratio, avg_daily_posts_30d,
                   reply_engagement_rate, account_age_days_log, has_shop_link, is_nsfw,
                   is_multi_platform, market_tier_high, market_tier_mid, market_tier_low,
                   content_furry, content_anime, content_vtuber, content_gaming,
                   content_webcomic, content_bl, content_gl, content_nsfw
               ) VALUES (
                   %(creator_id)s, %(followers_log)s, %(following_follower_ratio)s, %(avg_daily_posts_30d)s,
                   %(reply_engagement_rate)s, %(account_age_days_log)s, %(has_shop_link)s, %(is_nsfw)s,
                   %(is_multi_platform)s, %(market_tier_high)s, %(market_tier_mid)s, %(market_tier_low)s,
                   %(content_furry)s, %(content_anime)s, %(content_vtuber)s, %(content_gaming)s,
                   %(content_webcomic)s, %(content_bl)s, %(content_gl)s, %(content_nsfw)s
               )
               ON CONFLICT (creator_id) DO UPDATE SET
                   followers_log = EXCLUDED.followers_log,
                   following_follower_ratio = EXCLUDED.following_follower_ratio,
                   avg_daily_posts_30d = EXCLUDED.avg_daily_posts_30d,
                   reply_engagement_rate = EXCLUDED.reply_engagement_rate,
                   account_age_days_log = EXCLUDED.account_age_days_log,
                   has_shop_link = EXCLUDED.has_shop_link,
                   is_nsfw = EXCLUDED.is_nsfw,
                   is_multi_platform = EXCLUDED.is_multi_platform,
                   market_tier_high = EXCLUDED.market_tier_high,
                   market_tier_mid = EXCLUDED.market_tier_mid,
                   market_tier_low = EXCLUDED.market_tier_low,
                   content_furry = EXCLUDED.content_furry,
                   content_anime = EXCLUDED.content_anime,
                   content_vtuber = EXCLUDED.content_vtuber,
                   content_gaming = EXCLUDED.content_gaming,
                   content_webcomic = EXCLUDED.content_webcomic,
                   content_bl = EXCLUDED.content_bl,
                   content_gl = EXCLUDED.content_gl,
                   content_nsfw = EXCLUDED.content_nsfw,
                   calculated_at = NOW()""",
            features,
        )
    return True


def main() -> dict:
    rows = fetch_all(
        """SELECT id FROM creators
           WHERE (is_seed = true OR bd_decision = 'interested')
             AND id IN (SELECT creator_id FROM creator_features)"""
    )
    logger.info("Backfilling DNA features for %d creators", len(rows))

    success = 0
    for row in rows:
        try:
            if backfill_one(row["id"]):
                success += 1
        except Exception:
            logger.exception("Failed to backfill DNA features for creator %d", row["id"])

    logger.info("Backfilled %d/%d creators", success, len(rows))

    # Train DNA model
    try:
        meta = train_model_dna()
        logger.info("DNA model trained: %s", meta)
        return {"backfilled": success, "model_meta": meta}
    except Exception:
        logger.exception("Failed to train DNA model")
        return {"backfilled": success, "model_meta": None}


if __name__ == "__main__":
    result = main()
    print(result)
