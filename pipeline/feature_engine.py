"""10 维指标计算引擎 — 基于 Profile + Tweets 数据计算创作者特征。

计算结果写入 creator_features 表 (UNIQUE on creator_id)。
"""

import logging
import math
from collections import Counter
from urllib.parse import urlparse

import yaml

from config.settings import BIO_RULES_PATH
from db.connection import fetch_all, fetch_one, get_cursor

logger = logging.getLogger(__name__)

_bio_rules: dict | None = None


def _load_bio_rules() -> dict:
    global _bio_rules
    if _bio_rules is None:
        with open(BIO_RULES_PATH, encoding="utf-8") as f:
            _bio_rules = yaml.safe_load(f)
    return _bio_rules


def circle_influence_score_from_seed_connections(seed_connections: int) -> float:
    """Miner 7.0 圈层影响力分数，替代原 fan_creator_ratio。

    归一化到 0-100，与 Hub 阈值 (>=5 个 Seed) 对齐：5 个及以上 -> 100 分。
    """
    n = max(0, int(seed_connections))
    return min(100.0, float(n) * 20.0)


# ------------------------------------------------------------------
# 10 维指标计算
# ------------------------------------------------------------------

def calc_audience(followers: int) -> float:
    """min(log10(followers+1) * 20, 100)"""
    return min(math.log10(max(followers, 0) + 1) * 20.0, 100.0)


def calc_engagement(avg_likes: float, avg_rt: float, avg_replies: float, followers: int) -> float:
    """min((avg_likes + avg_rt*2 + avg_replies*3) / followers * 100, 100)"""
    if followers <= 0:
        return 0.0
    raw = (avg_likes + avg_rt * 2 + avg_replies * 3) / followers * 100
    return min(raw, 100.0)


def calc_virality(top3_avg: float, monthly_avg: float) -> float:
    """min(top3_avg / monthly_avg, 10) * 10"""
    if monthly_avg <= 0:
        return 0.0
    ratio = min(top3_avg / monthly_avg, 10.0)
    return ratio * 10.0


def calc_posting(monthly_posts: int) -> float:
    """min(monthly_posts / 30 * 100, 100)"""
    return min(max(monthly_posts, 0) / 30.0 * 100.0, 100.0)


def calc_monetization(bio: str, website: str) -> float:
    """Score based on bio_rules.yaml Link DNA + action keywords."""
    rules = _load_bio_rules()
    text = f"{bio} {website}".lower()

    commerce_links = ["booth.pm", "etsy.com/shop", "gumroad.com", "ko-fi.com", "patreon.com"]
    if any(link in text for link in commerce_links):
        return 90.0

    action_kws: list[str] = []
    for lang_list in rules.get("semantic_matrix", {}).get("action_keywords", {}).values():
        action_kws.extend(kw.lower() for kw in lang_list)
    if any(kw in text for kw in action_kws):
        return 60.0

    weak = ["shop", "store", "🛍️"]
    if any(s in text for s in weak):
        return 30.0

    return 0.0


def calc_growth() -> float:
    """Growth score — requires 30-day historical data; placeholder for v1.0."""
    return 50.0


def calc_character_consistency(tweets: list[dict]) -> float:
    """Simplified: domain concentration of image URLs across tweets."""
    domains: list[str] = []
    for tw in tweets:
        for url in (tw.get("media_urls") or []):
            try:
                d = urlparse(url).netloc
                if d:
                    domains.append(d)
            except Exception:
                pass

    if len(domains) < 2:
        return 50.0

    counts = Counter(domains)
    top_ratio = counts.most_common(1)[0][1] / len(domains)
    return min(top_ratio * 100.0, 100.0)


def calc_community(mentions: int, fanart_count: int, max_community: int = 100) -> float:
    """min((mentions*2 + fanart*5) / max_community * 100, 100)"""
    if max_community <= 0:
        return 0.0
    raw = (mentions * 2 + fanart_count * 5) / max_community * 100
    return min(raw, 100.0)


def calc_data_confidence(account_age_years: float, profile_completeness: float) -> float:
    """min(account_age*0.6 + completeness*0.4, 1.0) * 100"""
    score = min(account_age_years * 0.6 + profile_completeness * 0.4, 1.0)
    return score * 100.0


# ------------------------------------------------------------------
# 高层 API
# ------------------------------------------------------------------

def compute_features_for_creator(creator_id: int) -> dict | None:
    """Compute all 10 features for one creator and upsert into creator_features."""
    creator = fetch_one("SELECT * FROM creators WHERE id = %s", (creator_id,))
    if not creator:
        return None

    tweets = fetch_all(
        "SELECT * FROM tweets WHERE creator_id = %s ORDER BY created_at DESC",
        (creator_id,),
    )

    followers = creator.get("followers") or 0
    bio = creator.get("bio") or ""
    website = creator.get("website") or ""

    likes = [t.get("likes") or 0 for t in tweets]
    rts = [t.get("retweets") or 0 for t in tweets]
    replies = [t.get("replies") or 0 for t in tweets]

    avg_likes = sum(likes) / len(likes) if likes else 0
    avg_rt = sum(rts) / len(rts) if rts else 0
    avg_replies = sum(replies) / len(replies) if replies else 0

    engagement_vals = [l + r * 2 + rp * 3 for l, r, rp in zip(likes, rts, replies)]
    sorted_eng = sorted(engagement_vals, reverse=True)
    top3_avg = sum(sorted_eng[:3]) / min(len(sorted_eng), 3) if sorted_eng else 0
    monthly_avg = sum(engagement_vals) / len(engagement_vals) if engagement_vals else 0

    # Seed connections for circle influence
    seed_row = fetch_one(
        """SELECT COUNT(*) AS cnt FROM creator_graph cg
           JOIN creators c ON c.id = cg.creator_id
           WHERE cg.connected_creator_id = %s AND c.is_seed = true""",
        (creator_id,),
    )
    seed_connections = int(seed_row["cnt"]) if seed_row else 0

    # Mentions / fanart proxy from tweets
    mentions = sum(1 for t in tweets if "@" in (t.get("text") or ""))
    fanart_count = sum(1 for t in tweets if "fanart" in (t.get("text") or "").lower())

    account_age_years = (creator.get("account_age") or 1) / 365.0
    has_bio = 1.0 if bio else 0.0
    has_website = 1.0 if website else 0.0
    profile_completeness = (has_bio * 0.5 + has_website * 0.3 + (0.2 if followers > 0 else 0.0))

    features = {
        "audience_score": calc_audience(followers),
        "engagement_score": calc_engagement(avg_likes, avg_rt, avg_replies, followers),
        "virality_score": calc_virality(top3_avg, monthly_avg),
        "posting_score": calc_posting(len(tweets)),
        "monetization_score": calc_monetization(bio, website),
        "growth_score": calc_growth(),
        "circle_influence_score": circle_influence_score_from_seed_connections(seed_connections),
        "character_consistency": calc_character_consistency(tweets),
        "community_score": calc_community(mentions, fanart_count),
        "data_confidence": calc_data_confidence(account_age_years, profile_completeness),
    }

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO creator_features
                   (creator_id, audience_score, engagement_score, virality_score,
                    growth_score, posting_score, monetization_score,
                    circle_influence_score, character_consistency,
                    community_score, data_confidence)
               VALUES (%(cid)s, %(audience_score)s, %(engagement_score)s, %(virality_score)s,
                       %(growth_score)s, %(posting_score)s, %(monetization_score)s,
                       %(circle_influence_score)s, %(character_consistency)s,
                       %(community_score)s, %(data_confidence)s)
               ON CONFLICT (creator_id) DO UPDATE SET
                   audience_score = EXCLUDED.audience_score,
                   engagement_score = EXCLUDED.engagement_score,
                   virality_score = EXCLUDED.virality_score,
                   growth_score = EXCLUDED.growth_score,
                   posting_score = EXCLUDED.posting_score,
                   monetization_score = EXCLUDED.monetization_score,
                   circle_influence_score = EXCLUDED.circle_influence_score,
                   character_consistency = EXCLUDED.character_consistency,
                   community_score = EXCLUDED.community_score,
                   data_confidence = EXCLUDED.data_confidence,
                   calculated_at = NOW()""",
            {"cid": creator_id, **features},
        )

    return {"creator_id": creator_id, "seed_connections": seed_connections, **features}


def compute_all_pending() -> int:
    """Compute features for all deep-scraped creators without features yet."""
    rows = fetch_all(
        """SELECT DISTINCT c.id FROM creators c
           JOIN tweets t ON t.creator_id = c.id
           LEFT JOIN creator_features cf ON cf.creator_id = c.id
           WHERE cf.id IS NULL"""
    )
    count = 0
    for row in rows:
        result = compute_features_for_creator(row["id"])
        if result:
            count += 1
    logger.info("Computed features for %d creators", count)
    return count
