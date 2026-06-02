"""9 维指标计算引擎 — 基于 Profile + Tweets 数据计算创作者特征。

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
# 9 维指标计算
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


def calc_social_engagement_rate(tweets: list[dict], followers: int) -> float:
    """(avg_likes + avg_retweets) / followers * 100

    反映内容传播力——粉丝对内容的被动认可（点赞、转发）。
    """
    if followers <= 0 or not tweets:
        return 0.0
    total_likes = sum(float(tw.get("likes") or 0) for tw in tweets)
    total_rts = sum(float(tw.get("retweets") or 0) for tw in tweets)
    avg_likes = total_likes / len(tweets)
    avg_rts = total_rts / len(tweets)
    return (avg_likes + avg_rts) / followers * 100.0


def calc_conversation_rate(tweets: list[dict], followers: int) -> float:
    """avg_replies / followers * 100

    反映作者与粉丝的深度互动率——粉丝愿意在帖子下与作者对话。
    """
    if followers <= 0 or not tweets:
        return 0.0
    total_replies = sum(float(tw.get("replies") or 0) for tw in tweets)
    avg_replies = total_replies / len(tweets)
    return avg_replies / followers * 100.0


def calc_fanart_ratio(tweets: list[dict]) -> float:
    """fanart_tweets / total_tweets * 100"""
    if not tweets:
        return 0.0
    fanart_count = 0
    for tw in tweets:
        text = (tw.get("text") or "").lower()
        if "fanart" in text or "#fanart" in text or "fan art" in text:
            fanart_count += 1
    return fanart_count / len(tweets) * 100.0


def calc_virality_raw(top3_avg: float, monthly_avg: float) -> float:
    """top3_avg / monthly_avg，不封顶。

    替代 capped virality_score，保留异常爆款信号。
    """
    if monthly_avg <= 0:
        return 0.0
    return top3_avg / monthly_avg


def calc_monthly_engagement_base(monthly_avg: float) -> float:
    """保留 monthly_avg 绝对值作为 virality_raw_ratio 的基数参考。"""
    return monthly_avg


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


def calc_growth(creator_id: int, is_seed: bool = False) -> float:
    """Growth score — delegates to growth_monitor."""
    from pipeline.growth_monitor import calc_growth as _calc

    score, _ = _calc(creator_id, is_seed)
    return score


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


_MULTI_PLATFORM_DOMAINS: tuple[str, ...] = (
    "instagram.com", "twitch.tv", "youtube.com", "pixiv.net",
    "booth.pm", "etsy.com", "patreon.com", "fanbox.cc",
    "skeb.jp", "artstation.com", "tiktok.com", "linkedin.com",
    "behance.net", "discord.gg", "reddit.com", "carrd.co",
    "ko-fi.com", "buymeacoffee.com", "linktr.ee", "lit.link",
    "taplink.cc", "toyhou.se", "newgrounds.com", "furaffinity.net",
)


def calc_audience_segment(bio: str, website: str, username: str) -> tuple[float, str]:
    """计算受众分段评分与分类标签。

    Returns:
        (score, segment): score 用于模型输入，segment 用于业务展示。
        - multi_platform: 80.0
        - mainstream:     50.0
        - nsfw:           20.0
    """
    bio_text = bio or ""
    username_text = username or ""
    combined_lower = (bio_text + " " + username_text).lower()

    # 优先级 1: 成人向（NSFW 或 🔞）
    if "nsfw" in combined_lower or "🔞" in bio_text or "🔞" in username_text:
        return 20.0, "nsfw"

    # 优先级 2: 多平台（bio / website 中包含其他平台链接）
    all_text = (bio_text + " " + (website or "")).lower()
    if any(d in all_text for d in _MULTI_PLATFORM_DOMAINS):
        return 80.0, "multi_platform"

    # 默认: 正常销量创作者
    return 50.0, "mainstream"


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


# ------------------------------------------------------------------
# 高层 API
# ------------------------------------------------------------------

def compute_features_for_creator(creator_id: int) -> dict | None:
    """Compute all 9 features for one creator and upsert into creator_features."""
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

    audience_segment_score, segment = calc_audience_segment(bio, website, creator.get("username") or "")

    social_engagement_rate = calc_social_engagement_rate(tweets, followers)
    conversation_rate = calc_conversation_rate(tweets, followers)
    fanart_ratio = calc_fanart_ratio(tweets)
    virality_raw_ratio = calc_virality_raw(top3_avg, monthly_avg)
    monthly_engagement_base = calc_monthly_engagement_base(monthly_avg)

    features = {
        "audience_score": calc_audience(followers, following),
        "engagement_score": calc_engagement(tweets, followers),
        "virality_score": calc_virality(top3_avg, monthly_avg),
        "posting_score": calc_posting(tweets),
        "monetization_score": calc_monetization(bio, website),
        "growth_score": calc_growth(creator_id, bool(creator.get("is_seed"))),
        "character_consistency": calc_character_consistency(tweets),
        "community_score": calc_community(tweets),
        "audience_segment_score": audience_segment_score,
        "social_engagement_rate": social_engagement_rate,
        "conversation_rate": conversation_rate,
        "fanart_ratio": fanart_ratio,
        "virality_raw_ratio": virality_raw_ratio,
        "monthly_engagement_base": monthly_engagement_base,
    }

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO creator_features
                   (creator_id, audience_score, engagement_score, virality_score,
                    growth_score, posting_score, monetization_score,
                    character_consistency, community_score, audience_segment_score,
                    social_engagement_rate, conversation_rate, fanart_ratio,
                    virality_raw_ratio, monthly_engagement_base)
               VALUES (%(cid)s, %(audience_score)s, %(engagement_score)s, %(virality_score)s,
                       %(growth_score)s, %(posting_score)s, %(monetization_score)s,
                       %(character_consistency)s, %(community_score)s, %(audience_segment_score)s,
                       %(social_engagement_rate)s, %(conversation_rate)s, %(fanart_ratio)s,
                       %(virality_raw_ratio)s, %(monthly_engagement_base)s)
               ON CONFLICT (creator_id) DO UPDATE SET
                   audience_score = EXCLUDED.audience_score,
                   engagement_score = EXCLUDED.engagement_score,
                   virality_score = EXCLUDED.virality_score,
                   growth_score = EXCLUDED.growth_score,
                   posting_score = EXCLUDED.posting_score,
                   monetization_score = EXCLUDED.monetization_score,
                   character_consistency = EXCLUDED.character_consistency,
                   community_score = EXCLUDED.community_score,
                   audience_segment_score = EXCLUDED.audience_segment_score,
                   social_engagement_rate = EXCLUDED.social_engagement_rate,
                   conversation_rate = EXCLUDED.conversation_rate,
                   fanart_ratio = EXCLUDED.fanart_ratio,
                   virality_raw_ratio = EXCLUDED.virality_raw_ratio,
                   monthly_engagement_base = EXCLUDED.monthly_engagement_base,
                   calculated_at = NOW()""",
            {"cid": creator_id, **features},
        )

        # 同步更新 creators 表的分类标签
        cur.execute(
            "UPDATE creators SET creator_segment = %s WHERE id = %s AND creator_segment IS DISTINCT FROM %s",
            (segment, creator_id, segment),
        )

    return {"creator_id": creator_id, **features}


def backfill_audience_segment_for_existing_features() -> int:
    """为已有 creator_features 但缺少 audience_segment_score 的存量记录补算。

    部署新增特征列后，存量记录不会自动获得新值；此函数幂等补算。
    """
    rows = fetch_all(
        """SELECT c.id, c.username, c.bio, c.website
           FROM creators c
           JOIN creator_features cf ON cf.creator_id = c.id
           WHERE cf.audience_segment_score IS NULL"""
    )
    updated = 0
    for r in rows:
        score, segment = calc_audience_segment(
            r.get("bio") or "", r.get("website") or "", r.get("username") or ""
        )
        with get_cursor() as cur:
            cur.execute(
                "UPDATE creator_features SET audience_segment_score = %s WHERE creator_id = %s",
                (score, r["id"]),
            )
            cur.execute(
                "UPDATE creators SET creator_segment = %s WHERE id = %s AND creator_segment IS DISTINCT FROM %s",
                (segment, r["id"], segment),
            )
        updated += 1
    if updated:
        logger.info("Backfilled audience_segment_score for %d existing creators", updated)
    return updated


def backfill_missing_features() -> int:
    """Backfill creator_features for all creators that have tweets but no features yet.

    This is a standalone entry point for cron jobs and deployment scripts.
    """
    return compute_all_pending()


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
