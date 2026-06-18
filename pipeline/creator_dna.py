"""创作者 DNA 分析模块。

为 is_seed=true 或 bd_decision='interested' 的创作者触发深度 Apify 抓取，
并通过 LLM 抽取形象标签、商业信号、地区购买力等信息。
结果写入 creators_detail（前端展示 + 原始数据）和 creator_features（SPS 模型输入）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

import yaml
from apify_client import ApifyClient

from config.settings import (
    APIFY_API_TOKEN,
    APIFY_CONFIG_PATH,
    CREATOR_DNA_ENABLED,
    DAILY_DNA_BUDGET_USD,
    DNA_APIFY_ENABLED,
    DNA_LLM_BATCH_SIZE,
    DNA_LLM_ENABLED,
    DNA_MAX_TWEETS_PER_CREATOR,
    DNA_PLACEHOLDER_CONTENT,
    MARKET_TIERS_PATH,
)
from db.connection import fetch_all, fetch_one, get_cursor, upsert_cost
from pipeline.ai_filter import LLMClient

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 常量与配置
# ------------------------------------------------------------------

_SHOP_DOMAINS: tuple[str, ...] = (
    "booth.pm", "etsy.com", "gumroad.com", "patreon.com", "fanbox.cc",
    "skeb.jp", "ko-fi.com", "buymeacoffee.com", "vgen.co", "vgen.ai",
    "shopify.com", "bigcartel.com", "storenvy.com", "selly.gg",
    "redbubble.com", "teepublic.com", "spreadshirt.com", "merchbyamazon.com",
    "amazon.com/shop", "amazon.jp",
)

_SOCIAL_DOMAINS: tuple[str, ...] = (
    "instagram.com", "twitch.tv", "youtube.com", "tiktok.com", "reddit.com",
    "discord.gg", "artstation.com", "behance.net", "deviantart.com",
    "newgrounds.com", "furaffinity.net", "pixiv.net", "carrd.co",
    "linktr.ee", "lit.link", "taplink.cc", "toyhou.se", "cohost.org",
    "bsky.app", "threads.net", "facebook.com", "tumblr.com",
)

_CONTENT_CLASSIFICATIONS: tuple[str, ...] = (
    "furry",        # Furry
    "anime",        # Anime
    "vtuber",       # VTuber / 虚拟 IP
    "gaming",       # Gaming / 游戏
    "webcomic",     # Webcomic / 连载漫画
    "bl",           # Boys' Love
    "gl",           # Girls' Love
    "nsfw",         # NSFW / 成人向
)

_LLM_SYSTEM_PROMPT = """\
你是一位二次元/插画创作者周边商品分析专家。请根据提供的创作者 Profile 和最近推文，
判断该创作者的内容分类标签，用于评估其原创周边/毛绒商品的受众匹配度。

可选内容分类（最多选 3 个）：
- furry：以拟人化动物角色（furry/兽人）为主
- anime：日式动漫/二次元风格角色
- vtuber：虚拟主播/虚拟偶像内容
- gaming：游戏相关内容、游戏角色同人
- webcomic：连载漫画、条漫作品
- bl：耽美、男性向同性浪漫内容
- gl：百合、女性向同性浪漫内容
- nsfw：成人向、R18、暴露/性暗示内容

注意：
- content_classifications 是数组，最多 3 个，最少 1 个
- 只从上述 8 个标签中选择，不要 invent 新标签
- 如果创作者同时涉及多种类型，选择最主要、最突出的 1-3 个
- nsfw 可以是单独分类，也可以和其他分类共存
- 返回严格 JSON，不要 Markdown 代码块

输出格式：
{
  "character_tags": {
    "content_classifications": ["furry", "anime"],
    "tags": ["cat", "animal_ears", "chibi"],
    "style_tags": ["chibi", "anime"],
    "theme_tags": ["cute", "pastel"]
  },
  "reason": "简短理由"
}
"""

_LLM_PROMPT_TEMPLATE = """\
分析以下 Twitter/X 创作者（@{username}）。

Profile：
{display_name}
Bio: {bio}
Location: {location}
Website: {website}
Followers: {followers}
Following: {following}
Tweets count: {tweets_count}

最近推文（按时间倒序）：
{tweets_text}

请返回严格 JSON。
"""

# ------------------------------------------------------------------
# 市场分层
# ------------------------------------------------------------------

_market_tiers: dict[str, list[str]] | None = None


def _load_market_tiers() -> dict[str, list[str]]:
    global _market_tiers
    if _market_tiers is None:
        with open(MARKET_TIERS_PATH, encoding="utf-8") as f:
            _market_tiers = yaml.safe_load(f) or {}
    return _market_tiers


def _determine_market_tier(
    country: str | None,
    region: str | None,
    location: str | None,
    bio: str | None = None,
    display_name: str | None = None,
) -> str:
    """根据地区信息 + bio 语言线索推断市场层级：high / mid / low。"""
    text = " ".join(filter(None, [country, region, location])).lower()

    # 优先用明确地区信息
    if text:
        tiers = _load_market_tiers()
        for tier in ("high", "mid", "low"):
            for keyword in tiers.get(tier, []):
                if keyword.lower() in text:
                    return tier

    # 地区为空时，从 bio / display_name 做语言/国家推断
    context = " ".join(filter(None, [bio, display_name])).lower()
    if not context:
        return "low"

    # 东亚语言线索
    # 日文平假名/片假名/常用汉字
    if any(c in context for c in "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへもやゆよらりるれろわをんアイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン"):
        return "high"  # 日本
    # 韩文
    if any("\uac00" <= c <= "\ud7af" for c in context):
        return "high"  # 韩国
    # 中文
    if any("\u4e00" <= c <= "\u9fff" for c in context):
        return "mid"  # 中国/台湾/香港等

    # 拉丁语系国家关键词
    high_en = ("usa", "us.", "america", "united states", "canada", "uk", "united kingdom",
               "england", "germany", "france", "italy", "spain", "netherlands", "australia",
               "new zealand", "japan", "korea", "singapore")
    mid_latam = ("mexico", "brazil", "argentina", "chile", "colombia", "peru")
    mid_sea = ("malaysia", "thailand", "indonesia", "philippines", "vietnam")
    low_sa = ("india", "pakistan", "bangladesh")

    if any(kw in context for kw in high_en):
        return "high"
    if any(kw in context for kw in mid_latam + mid_sea):
        return "mid"
    if any(kw in context for kw in low_sa):
        return "low"

    # 默认：英文 bio 高购买力市场占比高
    if any(c.isascii() for c in context[:100]):
        return "high"

    return "low"


# ------------------------------------------------------------------
# 商业信号解析
# ------------------------------------------------------------------

def _extract_shop_signals(
    bio: str | None,
    website: str | None,
    website_links: list[str] | None,
) -> tuple[bool, list[str]]:
    """从 bio、website、website_links 中识别店铺平台。"""
    text = " ".join(filter(None, [bio or "", website or ""])).lower()
    urls = [u.lower() for u in (website_links or [])]
    urls.extend(re.findall(r"https?://[^\s<>\"'{}|\\^`\[\]]+", text))

    platforms = set()
    for url in urls:
        for domain in _SHOP_DOMAINS:
            if domain in url:
                platforms.add(domain.replace(".com", "").replace(".pm", "").replace(".cc", "").replace(".co", "").replace(".ai", ""))

    # 从文本中补充平台关键词
    platform_keywords = {
        "booth": "booth",
        "etsy": "etsy",
        "gumroad": "gumroad",
        "patreon": "patreon",
        "fanbox": "fanbox",
        "skeb": "skeb",
        "ko-fi": "kofi",
        "buymeacoffee": "buymeacoffee",
        "vgen": "vgen",
        "shopify": "shopify",
        "redbubble": "redbubble",
        "teepublic": "teepublic",
    }
    for kw, platform in platform_keywords.items():
        if kw in text:
            platforms.add(platform)

    return bool(platforms), sorted(platforms)


def _extract_multi_platform(bio: str | None, website: str | None) -> bool:
    """判断是否为多平台创作者（bio/website 中有其他社交平台链接）。"""
    text = " ".join(filter(None, [bio or "", website or ""])).lower()
    return any(domain in text for domain in _SOCIAL_DOMAINS)


def _extract_nsfw(bio: str | None, username: str | None, tweets: list[dict]) -> bool:
    """判断是否为 NSFW 创作者。基于 bio、username、推文文本。"""
    texts = [bio or "", username or ""]
    for tw in tweets[:20]:
        texts.append(tw.get("text") or "")
    combined = " ".join(texts).lower()
    nsfw_signals = ["nsfw", "🔞", "18+", "adult content", "lewd", "ecchi", "hentai", "r18"]
    return any(sig in combined for sig in nsfw_signals)


def _extract_commission_status(bio: str | None) -> str | None:
    """从 bio 中推断接稿状态。"""
    if not bio:
        return None
    text = bio.lower()
    if any(k in text for k in ("commissions closed", "comm closed", "commissions: closed", "not accepting")):
        return "closed"
    if any(k in text for k in ("waitlist", "waiting list", "slot full", "queue full")):
        return "waitlist"
    if any(k in text for k in ("commissions open", "comm open", "commission open", "accepting commissions", "open for commission", "接稿", "依頼受付中")):
        return "open"
    if "commission" in text:
        return "open"
    return None


# ------------------------------------------------------------------
# 原始特征计算
# ------------------------------------------------------------------

def _parse_tweet_created_at(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return None


def _compute_raw_features(
    creator: dict,
    tweets: list[dict],
) -> dict[str, Any]:
    """从 creators + tweets 计算原始数值特征。"""
    followers = creator.get("followers") or 0
    following = creator.get("following") or 0
    account_age_days = creator.get("account_age_days") or creator.get("account_age") or 0

    # 发帖频率：近 30 天
    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)
    recent_tweets_30d = [
        tw for tw in tweets
        if _parse_tweet_created_at(tw.get("created_at")) and _parse_tweet_created_at(tw.get("created_at")) >= cutoff_30d
    ]
    avg_daily_posts_30d = len(recent_tweets_30d) / 30.0

    # 互动率
    total_replies = sum(float(tw.get("replies") or 0) for tw in tweets)
    total_likes = sum(float(tw.get("likes") or 0) for tw in tweets)
    total_retweets = sum(float(tw.get("retweets") or 0) for tw in tweets)
    n_tweets = len(tweets) or 1

    reply_engagement_rate = (total_replies / n_tweets) / max(followers, 1)
    like_engagement_rate = (total_likes / n_tweets) / max(followers, 1)
    retweet_engagement_rate = (total_retweets / n_tweets) / max(followers, 1)

    return {
        "followers_log": math.log1p(followers),
        "following_follower_ratio": following / max(followers, 1),
        "avg_daily_posts_30d": avg_daily_posts_30d,
        "reply_engagement_rate": reply_engagement_rate,
        "like_engagement_rate": like_engagement_rate,
        "retweet_engagement_rate": retweet_engagement_rate,
        "account_age_days_log": math.log1p(max(account_age_days, 0)),
    }


# ------------------------------------------------------------------
# LLM 分析
# ------------------------------------------------------------------

def _build_llm_messages(creator: dict, tweets: list[dict]) -> list[dict]:
    """为 LLM 构建 prompt messages。"""
    recent = sorted(
        tweets,
        key=lambda tw: _parse_tweet_created_at(tw.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:DNA_MAX_TWEETS_PER_CREATOR]

    tweets_text = "\n---\n".join(
        f"[{tw.get('created_at')}] {tw.get('text') or ''}"
        for tw in recent
    ) or "无推文"

    prompt = _LLM_PROMPT_TEMPLATE.format(
        username=creator.get("handle") or creator.get("platform_account_id") or creator.get("username") or "",
        display_name=creator.get("display_name") or creator.get("username") or "",
        bio=creator.get("bio") or "",
        location=creator.get("location") or "",
        website=creator.get("website") or "",
        followers=creator.get("followers") or 0,
        following=creator.get("following") or 0,
        tweets_count=creator.get("tweets_count") or 0,
        tweets_text=tweets_text,
    )

    return [
        {"role": "system", "content": _LLM_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


def _parse_llm_result(text: str) -> dict | None:
    """解析 LLM 返回的 JSON。"""
    text = text.strip()
    if not text:
        return None

    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 兜底：提取最外层 JSON 对象
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _normalize_llm_result(result: dict) -> dict:
    """标准化 LLM 输出，只保留内容分类与形象标签。"""
    character = result.get("character_tags", {}) or {}

    # 内容分类：过滤非法值，最多保留 3 个
    classifications = character.get("content_classifications", []) or []
    valid = []
    for c in classifications:
        c = str(c).lower().strip()
        if c in _CONTENT_CLASSIFICATIONS and c not in valid:
            valid.append(c)
            if len(valid) >= 3:
                break
    if not valid:
        valid = ["anime"]

    return {
        "content_classifications": valid,
        "tags": list(character.get("tags", []) or []),
        "style_tags": list(character.get("style_tags", []) or []),
        "theme_tags": list(character.get("theme_tags", []) or []),
        "reason": result.get("reason", ""),
    }


async def _call_llm_with_fallback(messages: list[dict]) -> dict | None:
    """调用 LLM，带 provider fallback。"""
    from config.settings import FALLBACK_CHAIN, PROVIDER_CONFIGS, PROVIDER_MODELS

    clients: dict[str, LLMClient] = {}
    for provider in FALLBACK_CHAIN:
        cfg = PROVIDER_CONFIGS.get(provider, {})
        key = cfg.get("api_key", "")
        if key and "CHANGE_ME" not in key and key != "sk-placeholder":
            clients[provider] = LLMClient(provider)

    if not clients:
        logger.warning("No LLM providers configured for DNA analysis")
        return None

    last_error: Exception | None = None
    try:
        for provider in FALLBACK_CHAIN:
            client = clients.get(provider)
            if not client:
                continue
            try:
                resp = await client.chat(messages, temperature=0.0, max_tokens=2048)
                content = resp.get("content", "").strip()
                if content:
                    return {
                        "content": content,
                        "provider": provider,
                        "model": PROVIDER_MODELS.get(provider, "unknown"),
                        "usage": resp.get("usage", {}),
                    }
            except Exception as e:
                last_error = e
                logger.warning("DNA LLM provider %s failed: %s", provider, e)
                continue
    finally:
        for client in clients.values():
            try:
                await client._client.aclose()
            except RuntimeError:
                # event loop 已关闭，忽略
                pass
            except Exception:
                pass

    logger.error("All DNA LLM providers failed. Last error: %s", last_error)
    return None


# ------------------------------------------------------------------
# Apify 采集
# ------------------------------------------------------------------

def _trigger_apify_dna(usernames: list[str]) -> tuple[list[dict], float]:
    """触发 Apify DNA Actor 抓取推文，返回 items 和花费。"""
    if not usernames:
        return [], 0.0

    with open(APIFY_CONFIG_PATH, encoding="utf-8") as f:
        apify_cfg = yaml.safe_load(f)

    dna_cfg = apify_cfg.get("dna_actor", {})
    actor_id = dna_cfg.get("actor_id", "apidojo/tweet-scraper")
    actor_input = dna_cfg.get("input", {}).copy()

    # 填充 handles
    for key in ("twitterHandles", "usernames", "handles"):
        if key in actor_input:
            actor_input[key] = usernames
            break

    # apidojo/tweet-scraper 的 maxItems 是全局计数
    if "apidojo" in actor_id:
        actor_input["maxItems"] = max(
            actor_input.get("maxItems", 500),
            len(usernames) * DNA_MAX_TWEETS_PER_CREATOR,
        )

    client = ApifyClient(APIFY_API_TOKEN)
    run = client.actor(actor_id).call(run_input=actor_input)
    run_id = run.get("id", "")
    usage_usd = float(run.get("usageTotalUsd") or 0.0)
    if usage_usd > 0:
        upsert_cost(date.today(), apify_cost_usd=usage_usd)

    dataset_id = run.get("defaultDatasetId")
    items = []
    if dataset_id:
        items = list(client.dataset(dataset_id).iterate_items())

    logger.info("DNA Apify run %s: %d items, $%.4f", run_id, len(items), usage_usd)
    return items, usage_usd


def _store_apify_dna_results(items: list[dict]) -> dict[str, list[dict]]:
    """解析 Apify 返回的 tweets，按作者分组，更新 creators 表和 creators_detail.raw_profile。"""
    by_author: dict[str, list[dict]] = defaultdict(list)
    author_info: dict[str, dict] = {}

    for item in items:
        author = item.get("author") or {}
        username = (author.get("userName") or author.get("username") or "").lstrip("@").lower()
        if not username:
            username = (item.get("userName") or item.get("username") or "").lstrip("@").lower()
        if not username:
            continue
        by_author[username].append(item)
        if username not in author_info:
            author_info[username] = author

    updated_creators: dict[int, dict] = {}
    for username, tweets in by_author.items():
        author = author_info[username]
        with get_cursor() as cur:
            cur.execute(
                """UPDATE creators SET
                       followers = COALESCE(%s, followers),
                       following = COALESCE(%s, following),
                       tweets_count = COALESCE(%s, tweets_count),
                       bio = COALESCE(NULLIF(%s, ''), creators.bio),
                       website = COALESCE(NULLIF(%s, ''), creators.website)
                   WHERE platform_account_id = %s OR username = %s
                   RETURNING id""",
                (
                    author.get("followers") or author.get("followersCount"),
                    author.get("following") or author.get("friendsCount"),
                    author.get("statusesCount") or author.get("tweetsCount"),
                    author.get("description") or author.get("bio") or "",
                    author.get("website") or "",
                    username,
                    username,
                ),
            )
            row = cur.fetchone()
            if row:
                updated_creators[row["id"]] = author

    # 把 raw_profile 写入 creators_detail
    for creator_id, author in updated_creators.items():
        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO creators_detail (creator_id, raw_profile, last_synced_at)
                   VALUES (%s, %s, NOW())
                   ON CONFLICT (creator_id) DO UPDATE SET
                       raw_profile = COALESCE(EXCLUDED.raw_profile, creators_detail.raw_profile),
                       last_synced_at = NOW()""",
                (creator_id, json.dumps(author, ensure_ascii=False, default=str)),
            )

    return dict(by_author)


def _upsert_tweets(creator_id: int, tweets: list[dict]) -> int:
    """将 Apify 抓取的 tweets 写入 tweets 表。"""
    inserted = 0
    for tw in tweets:
        tweet_id = str(tw.get("id") or tw.get("id_str") or "")
        if not tweet_id:
            continue

        media_urls: list[str] = []
        media_types: list[str] = []
        for m in tw.get("extendedEntities", {}).get("media", []):
            url = m.get("media_url_https") or m.get("media_url") or ""
            mtype = m.get("type", "photo")
            if url:
                media_urls.append(url)
                media_types.append(mtype)

        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO tweets
                       (tweet_id, creator_id, likes, retweets, replies, views,
                        created_at, text, media_urls, media_types)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (tweet_id) DO NOTHING""",
                (
                    tweet_id,
                    creator_id,
                    tw.get("likeCount") or tw.get("likes") or 0,
                    tw.get("retweetCount") or tw.get("retweets") or 0,
                    tw.get("replyCount") or tw.get("replies") or 0,
                    tw.get("viewCount") or tw.get("views") or 0,
                    tw.get("createdAt") or tw.get("created_at"),
                    tw.get("text") or tw.get("full_text") or "",
                    media_urls or [],
                    media_types or [],
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
    return inserted


# ------------------------------------------------------------------
# 数据写入
# ------------------------------------------------------------------

def _write_creators_detail_dna(
    creator_id: int,
    dna: dict,
    raw_analysis: dict,
) -> None:
    """将 DNA 结构化数据写入 creators_detail。"""
    market_tier = dna.get("market_tier", "low")
    content_classifications = dna.get("content_classifications", ["anime"])

    # 合并 tags 到现有 tags
    existing = fetch_one(
        "SELECT tags FROM creators_detail WHERE creator_id = %s",
        (creator_id,),
    )
    existing_tags = set(existing.get("tags") or []) if existing else set()
    new_tags = set(dna.get("tags", []))
    merged_tags = sorted(existing_tags | new_tags)

    payload = {
        "creator_id": creator_id,
        "market_tier_high": market_tier == "high",
        "market_tier_mid": market_tier == "mid",
        "market_tier_low": market_tier == "low",
        "has_shop_link": dna.get("has_shop_link", False),
        "shop_platforms": dna.get("shop_platforms", []),
        "is_nsfw": dna.get("is_nsfw", False),
        "is_multi_platform": dna.get("is_multi_platform", False),
        "following_follower_ratio": dna.get("following_follower_ratio"),
        "avg_daily_posts_30d": dna.get("avg_daily_posts_30d"),
        "reply_engagement_rate": dna.get("reply_engagement_rate"),
        "account_age_days_log": dna.get("account_age_days_log"),
        "content_furry": "furry" in content_classifications,
        "content_anime": "anime" in content_classifications,
        "content_vtuber": "vtuber" in content_classifications,
        "content_gaming": "gaming" in content_classifications,
        "content_webcomic": "webcomic" in content_classifications,
        "content_bl": "bl" in content_classifications,
        "content_gl": "gl" in content_classifications,
        "content_nsfw": "nsfw" in content_classifications,
        "content_classifications": content_classifications,
        "tags": merged_tags,
        "style_tags": dna.get("style_tags", []),
        "theme_tags": dna.get("theme_tags", []),
        "raw_dna_analysis": json.dumps(raw_analysis, ensure_ascii=False, default=str),
        "last_synced_at": datetime.now(timezone.utc),
    }

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO creators_detail (
                   creator_id, market_tier_high, market_tier_mid, market_tier_low,
                   has_shop_link, shop_platforms, is_nsfw, is_multi_platform,
                   following_follower_ratio, avg_daily_posts_30d, reply_engagement_rate,
                   account_age_days_log,
                   content_furry, content_anime, content_vtuber, content_gaming,
                   content_webcomic, content_bl, content_gl, content_nsfw,
                   content_classifications, tags, style_tags, theme_tags,
                   raw_dna_analysis, last_synced_at
               ) VALUES (
                   %(creator_id)s, %(market_tier_high)s, %(market_tier_mid)s, %(market_tier_low)s,
                   %(has_shop_link)s, %(shop_platforms)s, %(is_nsfw)s, %(is_multi_platform)s,
                   %(following_follower_ratio)s, %(avg_daily_posts_30d)s, %(reply_engagement_rate)s,
                   %(account_age_days_log)s,
                   %(content_furry)s, %(content_anime)s, %(content_vtuber)s, %(content_gaming)s,
                   %(content_webcomic)s, %(content_bl)s, %(content_gl)s, %(content_nsfw)s,
                   %(content_classifications)s, %(tags)s, %(style_tags)s, %(theme_tags)s,
                   %(raw_dna_analysis)s, %(last_synced_at)s
               )
               ON CONFLICT (creator_id) DO UPDATE SET
                   market_tier_high = EXCLUDED.market_tier_high,
                   market_tier_mid = EXCLUDED.market_tier_mid,
                   market_tier_low = EXCLUDED.market_tier_low,
                   has_shop_link = COALESCE(EXCLUDED.has_shop_link, creators_detail.has_shop_link),
                   shop_platforms = COALESCE(EXCLUDED.shop_platforms, creators_detail.shop_platforms),
                   is_nsfw = EXCLUDED.is_nsfw,
                   is_multi_platform = EXCLUDED.is_multi_platform,
                   following_follower_ratio = EXCLUDED.following_follower_ratio,
                   avg_daily_posts_30d = EXCLUDED.avg_daily_posts_30d,
                   reply_engagement_rate = EXCLUDED.reply_engagement_rate,
                   account_age_days_log = EXCLUDED.account_age_days_log,
                   content_furry = EXCLUDED.content_furry,
                   content_anime = EXCLUDED.content_anime,
                   content_vtuber = EXCLUDED.content_vtuber,
                   content_gaming = EXCLUDED.content_gaming,
                   content_webcomic = EXCLUDED.content_webcomic,
                   content_bl = EXCLUDED.content_bl,
                   content_gl = EXCLUDED.content_gl,
                   content_nsfw = EXCLUDED.content_nsfw,
                   content_classifications = EXCLUDED.content_classifications,
                   tags = EXCLUDED.tags,
                   style_tags = EXCLUDED.style_tags,
                   theme_tags = EXCLUDED.theme_tags,
                   raw_dna_analysis = COALESCE(EXCLUDED.raw_dna_analysis, creators_detail.raw_dna_analysis),
                   last_synced_at = EXCLUDED.last_synced_at""",
            payload,
        )


def _write_creator_features_dna(creator_id: int, dna: dict) -> None:
    """将 DNA 数值特征写入 creator_features，供 SPS 模型使用。"""
    content_classifications = dna.get("content_classifications", ["anime"])

    features = {
        "creator_id": creator_id,
        "followers_log": dna.get("followers_log"),
        "following_follower_ratio": dna.get("following_follower_ratio"),
        "avg_daily_posts_30d": dna.get("avg_daily_posts_30d"),
        "reply_engagement_rate": dna.get("reply_engagement_rate"),
        "account_age_days_log": dna.get("account_age_days_log"),
        "has_shop_link": 1.0 if dna.get("has_shop_link") else 0.0,
        "is_nsfw": 1.0 if dna.get("is_nsfw") else 0.0,
        "is_multi_platform": 1.0 if dna.get("is_multi_platform") else 0.0,
        "market_tier_high": 1.0 if dna.get("market_tier") == "high" else 0.0,
        "market_tier_mid": 1.0 if dna.get("market_tier") == "mid" else 0.0,
        "market_tier_low": 1.0 if dna.get("market_tier") == "low" else 0.0,
        "content_furry": 1.0 if "furry" in content_classifications else 0.0,
        "content_anime": 1.0 if "anime" in content_classifications else 0.0,
        "content_vtuber": 1.0 if "vtuber" in content_classifications else 0.0,
        "content_gaming": 1.0 if "gaming" in content_classifications else 0.0,
        "content_webcomic": 1.0 if "webcomic" in content_classifications else 0.0,
        "content_bl": 1.0 if "bl" in content_classifications else 0.0,
        "content_gl": 1.0 if "gl" in content_classifications else 0.0,
        "content_nsfw": 1.0 if "nsfw" in content_classifications else 0.0,
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


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------

def _check_dna_budget() -> bool:
    """检查 DNA 日预算。"""
    row = fetch_one(
        "SELECT COALESCE(SUM(apify_cost_usd), 0) AS today FROM cost_tracking WHERE date = CURRENT_DATE"
    )
    today = float(row["today"]) if row else 0.0
    if today >= DAILY_DNA_BUDGET_USD:
        logger.warning("Daily DNA budget exceeded ($%.2f) — blocking", today)
        return False
    return True


def _get_eligible_creators(limit: int | None = None) -> list[dict]:
    """获取需要做 DNA 分析的种子或 interested 创作者。"""
    sql = """
        SELECT c.id, c.username
        FROM creators c
        LEFT JOIN creators_detail cd ON cd.creator_id = c.id
        WHERE (c.is_seed = true OR c.bd_decision = 'interested')
          AND (cd.raw_dna_analysis IS NULL OR cd.last_synced_at < NOW() - INTERVAL '30 days')
        ORDER BY c.first_seen_at ASC
    """
    params = ()
    if limit:
        sql += " LIMIT %s"
        params = (limit,)
    return fetch_all(sql, params)


def _ensure_enough_tweets(
    creator_id: int, handle: str, min_tweets: int = 30
) -> list[dict]:
    """确保创作者有足够推文。如果不足且 Apify 已启用，尝试触发抓取。"""
    tweets = fetch_all(
        "SELECT * FROM tweets WHERE creator_id = %s ORDER BY created_at DESC",
        (creator_id,),
    )
    if len(tweets) >= min_tweets:
        return tweets

    if not DNA_APIFY_ENABLED:
        logger.debug("DNA Apify disabled — using existing %d tweets for creator %d", len(tweets), creator_id)
        return tweets

    if not handle:
        return tweets

    if not _check_dna_budget():
        return tweets

    logger.info("DNA: fetching more tweets for @%s (current %d)", handle, len(tweets))
    items, _ = _trigger_apify_dna([handle])
    if items:
        by_author = _store_apify_dna_results(items)
        for username, author_tweets in by_author.items():
            # 找到对应 creator_id（优先用 platform_account_id 匹配）
            row = fetch_one(
                "SELECT id FROM creators WHERE platform_account_id = %s OR username = %s",
                (username, username),
            )
            if row:
                _upsert_tweets(row["id"], author_tweets)

    # 重新读取
    tweets = fetch_all(
        "SELECT * FROM tweets WHERE creator_id = %s ORDER BY created_at DESC",
        (creator_id,),
    )
    return tweets


def analyze_creator_dna(creator_id: int) -> dict | None:
    """分析单个创作者的 DNA，写入 creators_detail 和 creator_features。

    Returns: {"creator_id": int, "market_tier": str, "primary_species": str, ...}
    """
    if not CREATOR_DNA_ENABLED:
        logger.info("Creator DNA is disabled")
        return None

    creator = fetch_one("SELECT * FROM creators WHERE id = %s", (creator_id,))
    if not creator:
        logger.warning("Creator %d not found", creator_id)
        return None

    if not (creator.get("is_seed") or creator.get("bd_decision") == "interested"):
        logger.info("Creator %d is not seed or interested, skipping DNA", creator_id)
        return None

    # 使用 platform_account_id 作为真实 Twitter handle
    handle = (creator.get("platform_account_id") or creator.get("username") or "").lstrip("@").strip()
    if not handle:
        logger.warning("Creator %d has no valid handle, skipping DNA", creator_id)
        return None
    creator["handle"] = handle

    # 1. 确保有足够推文
    tweets = _ensure_enough_tweets(creator_id, handle, min_tweets=max(30, DNA_MAX_TWEETS_PER_CREATOR // 3))

    # 2. 计算原始特征
    raw_features = _compute_raw_features(creator, tweets)

    # 3. 基于规则提取商业信号（不依赖 LLM）
    bio = creator.get("bio") or ""
    website = creator.get("website") or ""
    username = creator.get("username") or ""

    # 从 creators_detail 读 website_links 如果存在
    detail = fetch_one("SELECT website_links FROM creators_detail WHERE creator_id = %s", (creator_id,))
    website_links = detail.get("website_links") if detail else None

    has_shop_link, shop_platforms = _extract_shop_signals(bio, website, website_links)
    is_multi_platform = _extract_multi_platform(bio, website)
    is_nsfw = _extract_nsfw(bio, username, tweets)
    commission_status = _extract_commission_status(bio)

    # 地区分层
    country = creator.get("country") or (detail.get("country") if detail else None)
    region = creator.get("region") or (detail.get("region") if detail else None)
    location = (detail.get("location") if detail else None) or creator.get("location")
    display_name = creator.get("display_name") or creator.get("username") or ""
    market_tier = _determine_market_tier(country, region, location, bio, display_name)

    # 4. LLM 分析（开发阶段可关闭，用占位符跑通链路）
    if DNA_LLM_ENABLED:
        llm_input = {
            **creator,
            "display_name": creator.get("display_name") or creator.get("username"),
            "location": location,
            "website": website,
        }
        messages = _build_llm_messages(llm_input, tweets)

        loop = asyncio.new_event_loop()
        try:
            llm_resp = loop.run_until_complete(_call_llm_with_fallback(messages))
        finally:
            loop.close()

        if llm_resp:
            llm_result = _parse_llm_result(llm_resp.get("content", ""))
            if llm_resp.get("usage"):
                total_tokens = llm_resp.get("usage", {}).get("total_tokens", 0)
                if total_tokens:
                    upsert_cost(date.today(), llm_tokens_used=total_tokens, llm_cost_usd=total_tokens * 0.000002)
        else:
            llm_result = None
    else:
        llm_result = None
        llm_resp = None

    if llm_result:
        llm_dna = _normalize_llm_result(llm_result)
        # LLM 输出内容分类 + 形象标签；地区/商业信号保持规则推断
        content_classifications = llm_dna.get("content_classifications", DNA_PLACEHOLDER_CONTENT)
        tags = llm_dna.get("tags", [])
        style_tags = llm_dna.get("style_tags", [])
        theme_tags = llm_dna.get("theme_tags", [])
        raw_analysis = {
            "llm_result": llm_result,
            "llm_provider": llm_resp.get("provider") if llm_resp else None,
            "llm_model": llm_resp.get("model") if llm_resp else None,
            "rule_signals": {
                "market_tier": market_tier,
                "has_shop_link": has_shop_link,
                "shop_platforms": shop_platforms,
                "commission_status": commission_status,
                "is_nsfw": is_nsfw,
                "is_multi_platform": is_multi_platform,
            },
        }
    else:
        # LLM 关闭或失败，用占位符兜底
        content_classifications = list(DNA_PLACEHOLDER_CONTENT)
        tags = []
        style_tags = []
        theme_tags = []
        raw_analysis = {
            "llm_skipped": not DNA_LLM_ENABLED,
            "llm_failed": DNA_LLM_ENABLED,
            "rule_signals": {
                "market_tier": market_tier,
                "has_shop_link": has_shop_link,
                "shop_platforms": shop_platforms,
                "commission_status": commission_status,
                "is_nsfw": is_nsfw,
                "is_multi_platform": is_multi_platform,
            },
        }

    # 5. 组装最终 DNA
    dna = {
        **raw_features,
        "market_tier": market_tier,
        "has_shop_link": has_shop_link,
        "shop_platforms": shop_platforms,
        "commission_status": commission_status,
        "is_nsfw": is_nsfw,
        "is_multi_platform": is_multi_platform,
        "content_classifications": content_classifications,
        "tags": tags,
        "style_tags": style_tags,
        "theme_tags": theme_tags,
    }

    # 6. 写入数据库
    _write_creators_detail_dna(creator_id, dna, raw_analysis)
    _write_creator_features_dna(creator_id, dna)

    logger.info("DNA analysis complete for creator %d: content=%s, tier=%s, shop=%s",
                creator_id, content_classifications, market_tier, has_shop_link)

    return {"creator_id": creator_id, **dna}


def analyze_pending_dna(limit: int | None = None) -> dict:
    """批量分析所有待处理的种子/interested 创作者。"""
    creators = _get_eligible_creators(limit)
    analyzed = failed = 0
    for c in creators:
        try:
            result = analyze_creator_dna(c["id"])
            if result:
                analyzed += 1
            else:
                failed += 1
        except Exception:
            logger.exception("DNA analysis failed for creator %d", c["id"])
            failed += 1

    return {"total": len(creators), "analyzed": analyzed, "failed": failed}


def trigger_dna_for_creators(creator_ids: list[int]) -> dict:
    """为指定创作者触发 DNA 分析。"""
    analyzed = failed = 0
    for cid in creator_ids:
        try:
            result = analyze_creator_dna(cid)
            if result:
                analyzed += 1
            else:
                failed += 1
        except Exception:
            logger.exception("DNA analysis failed for creator %d", cid)
            failed += 1
    return {"total": len(creator_ids), "analyzed": analyzed, "failed": failed}


def set_creator_content_classifications(
    creator_id: int,
    classifications: list[str],
    tags: list[str] | None = None,
    style_tags: list[str] | None = None,
    theme_tags: list[str] | None = None,
) -> None:
    """人工录入创作者的内容分类标签，并同步写入 creator_features。

    Args:
        classifications: 内容分类列表，如 ["furry", "anime"]
        tags: 形象标签数组（可选）
        style_tags: 视觉风格标签数组（可选）
        theme_tags: 主题标签数组（可选）
    """
    valid = []
    for c in classifications:
        c = str(c).lower().strip()
        if c in _CONTENT_CLASSIFICATIONS and c not in valid:
            valid.append(c)
            if len(valid) >= 3:
                break
    if not valid:
        valid = list(DNA_PLACEHOLDER_CONTENT)

    detail = fetch_one("SELECT * FROM creators_detail WHERE creator_id = %s", (creator_id,))
    creator = fetch_one("SELECT * FROM creators WHERE id = %s", (creator_id,))
    if not creator:
        raise ValueError(f"Creator {creator_id} not found")

    # 更新 creators_detail
    with get_cursor() as cur:
        cur.execute(
            """UPDATE creators_detail SET
                   content_furry = %s,
                   content_anime = %s,
                   content_vtuber = %s,
                   content_gaming = %s,
                   content_webcomic = %s,
                   content_bl = %s,
                   content_gl = %s,
                   content_nsfw = %s,
                   content_classifications = %s,
                   tags = COALESCE(%s, tags),
                   style_tags = COALESCE(%s, style_tags),
                   theme_tags = COALESCE(%s, theme_tags),
                   last_synced_at = NOW()
               WHERE creator_id = %s""",
            (
                "furry" in valid,
                "anime" in valid,
                "vtuber" in valid,
                "gaming" in valid,
                "webcomic" in valid,
                "bl" in valid,
                "gl" in valid,
                "nsfw" in valid,
                valid,
                tags,
                style_tags,
                theme_tags,
                creator_id,
            ),
        )

    # 同步更新 creator_features 中的 one-hot 列
    # 注意：这里只更新 content_* 列，不改动其他 DNA 数值特征
    with get_cursor() as cur:
        cur.execute(
            """UPDATE creator_features SET
                   content_furry = %s,
                   content_anime = %s,
                   content_vtuber = %s,
                   content_gaming = %s,
                   content_webcomic = %s,
                   content_bl = %s,
                   content_gl = %s,
                   content_nsfw = %s,
                   calculated_at = NOW()
               WHERE creator_id = %s""",
            (
                1.0 if "furry" in valid else 0.0,
                1.0 if "anime" in valid else 0.0,
                1.0 if "vtuber" in valid else 0.0,
                1.0 if "gaming" in valid else 0.0,
                1.0 if "webcomic" in valid else 0.0,
                1.0 if "bl" in valid else 0.0,
                1.0 if "gl" in valid else 0.0,
                1.0 if "nsfw" in valid else 0.0,
                creator_id,
            ),
        )

    logger.info("Manual content classifications set for creator %d: %s", creator_id, valid)
