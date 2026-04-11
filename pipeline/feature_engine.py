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


def _parse_tweet_created_at(value: object):
    """将推文时间统一为 UTC 带时区，避免与 utcnow 相减时出现 naive/aware 混用。"""
    from datetime import datetime, timezone

    if value is None:
        return None
    created = value
    if isinstance(created, str):
        try:
            created = datetime.fromisoformat(created.strip().replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            return None
    elif not isinstance(created, datetime):
        return None
    if created.tzinfo is None:
        return created.replace(tzinfo=timezone.utc)
    return created.astimezone(timezone.utc)


# ------------------------------------------------------------------
# 10 维指标计算
# ------------------------------------------------------------------

def calc_audience(followers: int, following: int = 0) -> float:
    """Audience score with bot/fake-follower correction.

    Penalize accounts with very high following/followers ratio (likely follow-for-follow).
    """
    if followers <= 0:
        return 0.0
    raw = min(math.log10(followers + 1) * 20.0, 100.0)
    if following > 0 and followers > 0:
        ratio = following / followers
        if ratio > 1.5:
            penalty = min((ratio - 1.5) * 20.0, 40.0)
            raw = max(raw - penalty, 0.0)
    return raw


def calc_engagement(tweets: list[dict], followers: int) -> float:
    """Engagement score with time-decay weighting.

    Recent tweets (< 7 days) get weight 1.0, 7-14 days get 0.7, 14-30 days get 0.4.
    """
    if followers <= 0 or not tweets:
        return 0.0

    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    total_weighted = 0.0
    total_weight = 0.0

    for tw in tweets:
        likes = float(tw.get("likes") or 0)
        rts = float(tw.get("retweets") or 0)
        replies = float(tw.get("replies") or 0)
        eng = likes + rts * 2 + replies * 3

        created = _parse_tweet_created_at(tw.get("created_at"))
        age_days = (now - created).days if created else 15
        if age_days < 7:
            weight = 1.0
        elif age_days < 14:
            weight = 0.7
        else:
            weight = 0.4

        total_weighted += eng * weight
        total_weight += weight

    if total_weight <= 0:
        return 0.0
    avg_eng = total_weighted / total_weight
    raw = avg_eng / followers * 100
    return min(raw, 100.0)


def calc_virality(top3_avg: float, monthly_avg: float) -> float:
    """min(top3_avg / monthly_avg, 10) * 10"""
    if monthly_avg <= 0:
        return 0.0
    ratio = min(top3_avg / monthly_avg, 10.0)
    return ratio * 10.0


def calc_posting(tweets: list[dict]) -> float:
    """Posting score based on actual 30-day tweet count and date range.

    If tweets span fewer than 30 days, scale proportionally.
    """
    if not tweets:
        return 0.0

    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)

    recent = []
    for tw in tweets:
        created = _parse_tweet_created_at(tw.get("created_at"))
        if created and created >= cutoff:
            recent.append(created)

    if not recent:
        return min(len(tweets) / 30.0 * 100.0, 100.0)

    date_range = (max(recent) - min(recent)).days + 1
    daily_rate = len(recent) / max(date_range, 1)
    monthly_estimate = daily_rate * 30
    return min(monthly_estimate / 30.0 * 100.0, 100.0)


def calc_monetization(bio: str, website: str) -> float:
    """Score based on bio_rules.yaml — uses BioRuleFilter for consistency."""
    from pipeline.bio_rule_filter import BioRuleFilter
    bf = BioRuleFilter()
    result = bf.filter(bio, website)

    if result["passed"] is True and result["level"] == 1:
        return 90.0
    if result["passed"] is True and result["confidence"] >= 0.80:
        return 70.0
    if result["passed"] is True:
        return 50.0
    if result["signals"]:
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


def calc_community(tweets: list[dict], max_community: int = 100) -> float:
    """Community score with fanart retweet weighting.

    Fanart retweets get 5x weight, regular mentions 2x, other retweets 1x.
    """
    if not tweets or max_community <= 0:
        return 0.0

    score = 0.0
    for tw in tweets:
        text = (tw.get("text") or "").lower()
        rts = float(tw.get("retweets") or 0)
        is_fanart = "fanart" in text or "#fanart" in text or "fan art" in text
        has_mention = "@" in text

        if is_fanart:
            score += (1 + rts * 0.5) * 5
        elif has_mention:
            score += 2
        else:
            score += rts * 0.1

    raw = score / max_community * 100
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
    following = creator.get("following") or 0
    bio = creator.get("bio") or ""
    website = creator.get("website") or ""

    engagement_vals = [
        (t.get("likes") or 0) + (t.get("retweets") or 0) * 2 + (t.get("replies") or 0) * 3
        for t in tweets
    ]
    sorted_eng = sorted(engagement_vals, reverse=True)
    top3_avg = sum(sorted_eng[:3]) / min(len(sorted_eng), 3) if sorted_eng else 0
    monthly_avg = sum(engagement_vals) / len(engagement_vals) if engagement_vals else 0

    seed_row = fetch_one(
        """SELECT COUNT(*) AS cnt FROM creator_graph cg
           JOIN creators c ON c.id = cg.creator_id
           WHERE cg.connected_creator_id = %s AND c.is_seed = true""",
        (creator_id,),
    )
    seed_connections = int(seed_row["cnt"]) if seed_row else 0

    account_age_years = (creator.get("account_age") or 1) / 365.0
    has_bio = 1.0 if bio else 0.0
    has_website = 1.0 if website else 0.0
    profile_completeness = (has_bio * 0.5 + has_website * 0.3 + (0.2 if followers > 0 else 0.0))

    features = {
        "audience_score": calc_audience(followers, following),
        "engagement_score": calc_engagement(tweets, followers),
        "virality_score": calc_virality(top3_avg, monthly_avg),
        "posting_score": calc_posting(tweets),
        "monetization_score": calc_monetization(bio, website),
        "growth_score": calc_growth(),
        "circle_influence_score": circle_influence_score_from_seed_connections(seed_connections),
        "character_consistency": calc_character_consistency(tweets),
        "community_score": calc_community(tweets),
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
