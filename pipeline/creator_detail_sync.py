"""高价值创作者详情档案同步 — 维护 creators_detail 表。

仅收录两类创作者：
  1. is_seed = true 的种子创作者
  2. bd_decision = 'interested' 的 BD 已确认创作者

同步逻辑：
  - 从 creators / creator_features / creator_content_analysis / tweets 聚合信息
  - 解析 bio 中的链接、邮箱、接稿状态、标签
  - 将 location 拆分为 location / country / region（简单规则）
  - 将 creator_type 与关键词映射为 tags
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from db.connection import fetch_all, fetch_one, get_cursor

logger = logging.getLogger(__name__)

# 创作者类型 → 可读标签
_CREATOR_TYPE_TAGS: dict[str, str] = {
    "oc_creator": "OC",
    "vtuber": "VTuber",
    "fan_artist": "Fan Artist",
    "game_creator": "Game Creator",
    "content_creator": "Content Creator",
    "unknown": "Unknown",
}

# 简单作品/业务关键词标签（bio / website 中出现即加入）
_WORK_TAGS_KEYWORDS: dict[str, list[str]] = {
    "OC": ["original character", "oc creator", "my oc", "oc art"],
    "Fanart": ["fanart", "fan art", "doujin", "同人"],
    "VTuber": ["vtuber", "virtual youtuber", "虚拟主播", "live2d"],
    "Plush": ["plush", "plushie", "ぬいぐるみ", "doll maker"],
    "Merch": ["merch", "store", "shop", "booth.pm", "etsy.com", "gumroad", "patreon"],
    "Commission": ["commission", "comm open", "接稿", "依頼"],
    "Pre-order": ["preorder", "pre-order", "预售", "preorder open"],
}

# 常见国家/地区推断规则（location 字段包含关键词即命中）
_COUNTRY_RULES: list[tuple[list[str], str, str | None]] = [
    # 亚洲
    (["japan", "tokyo", "osaka", "kyoto", "yokohama", "sapporo", "fukuoka", "nagoya", "kanagawa", "saitama", "chiba", "jpn"], "Japan", None),
    (["china", "beijing", "shanghai", "guangzhou", "shenzhen", "chengdu", "hangzhou", "wuhan", "xian"], "China", None),
    (["taiwan", "taipei", "taichung", "kaohsiung"], "Taiwan", None),
    (["hong kong"], "Hong Kong", None),
    (["korea", "seoul", "busan", "incheon"], "South Korea", None),
    (["singapore"], "Singapore", None),
    (["malaysia", "kuala lumpur"], "Malaysia", None),
    (["thailand", "bangkok"], "Thailand", None),
    (["vietnam", "hanoi", "ho chi minh"], "Vietnam", None),
    (["indonesia", "jakarta"], "Indonesia", None),
    (["philippines", "manila"], "Philippines", None),
    (["india", "mumbai", "delhi", "bangalore"], "India", None),
    # 北美
    (["usa", "united states", "america", "california", "new york", "texas", "florida", "illinois", "washington", "oregon", "colorado", "arizona", "nevada", "georgia", "michigan", "pennsylvania", "ohio", "north carolina", "new jersey", "virginia", "massachusetts", "tennessee", "indiana", "missouri", "maryland", "wisconsin", "minnesota", "colorado", "alabama", "south carolina", "louisiana", "kentucky", "oregon", "oklahoma", "connecticut", "utah", "iowa", "nevada", "arkansas", "mississippi", "kansas", "new mexico", "nebraska", "west virginia", "idaho", "hawaii", "new hampshire", "maine", "montana", "rhode island", "delaware", "south dakota", "north dakota", "alaska", "vermont", "wyoming"], "United States", None),
    (["canada", "toronto", "vancouver", "montreal", "calgary", "ottawa", "edmonton", "quebec"], "Canada", None),
    (["mexico", "mexico city", "guadalajara"], "Mexico", None),
    # 欧洲
    (["uk", "united kingdom", "england", "london", "manchester", "birmingham", "scotland", "wales", "northern ireland", "gb"], "United Kingdom", None),
    (["germany", "berlin", "munich", "hamburg", "cologne", "frankfurt", "de"], "Germany", None),
    (["france", "paris", "lyon", "marseille", "fr"], "France", None),
    (["italy", "rome", "milan", "naples"], "Italy", None),
    (["spain", "madrid", "barcelona", "valencia"], "Spain", None),
    (["netherlands", "amsterdam", "rotterdam"], "Netherlands", None),
    (["belgium", "brussels", "antwerp"], "Belgium", None),
    (["switzerland", "zurich", "geneva"], "Switzerland", None),
    (["austria", "vienna"], "Austria", None),
    (["poland", "warsaw", "krakow"], "Poland", None),
    (["sweden", "stockholm", "gothenburg"], "Sweden", None),
    (["norway", "oslo"], "Norway", None),
    (["denmark", "copenhagen"], "Denmark", None),
    (["finland", "helsinki"], "Finland", None),
    (["russia", "moscow", "saint petersburg"], "Russia", None),
    (["ukraine", "kyiv", "kiev"], "Ukraine", None),
    (["turkey", "istanbul", "ankara"], "Turkey", None),
    # 大洋洲
    (["australia", "sydney", "melbourne", "brisbane", "perth"], "Australia", None),
    (["new zealand", "auckland", "wellington", "christchurch"], "New Zealand", None),
    # 南美
    (["brazil", "sao paulo", "rio de janeiro"], "Brazil", None),
    (["argentina", "buenos aires"], "Argentina", None),
    (["chile", "santiago"], "Chile", None),
    (["colombia", "bogota"], "Colombia", None),
]

# 简单 email 正则
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# URL 正则（允许 http(s) 与部分无协议域名）
_URL_RE = re.compile(r"https?://[^\s<>\"'{}|\\^`\[\]]+|(?:www\.|[-a-zA-Z0-9]{2,}\.(?:com|co|net|org|io|cc|pm|jp|uk|de|fr|es|it|nl|be|ch|at|pl|se|no|dk|fi|ru|ua|tr|au|nz|br|ar|cl|co|sg|my|th|vn|id|ph|in|kr|cn|tw|hk|art|xyz|me|info|biz|dev|app|shop|store|studio|design|works))[^\s<>\"'{}|\\^`\[\]]*", re.IGNORECASE)

# 社交媒体域名（用于 social_links）—— 仅收录社交平台/作品集社区，商务平台通过 merch_links 体现
_SOCIAL_DOMAINS: dict[str, str] = {
    "instagram.com": "instagram",
    "twitch.tv": "twitch",
    "youtube.com": "youtube",
    "tiktok.com": "tiktok",
    "reddit.com": "reddit",
    "discord.gg": "discord",
    "artstation.com": "artstation",
    "behance.net": "behance",
    "deviantart.com": "deviantart",
    "newgrounds.com": "newgrounds",
    "furaffinity.net": "furaffinity",
    "twitter.com": "twitter",
    "x.com": "twitter",
}


def _normalize_username(raw: str) -> str:
    return raw.strip().lstrip("@").lower()


def _parse_location(location_str: str | None) -> tuple[str | None, str | None, str | None]:
    """从 Twitter location 字段推断 (country, region, cleaned_location)。

    Returns (country, region, location)
    """
    if not location_str:
        return None, None, None

    text = location_str.strip()
    if not text:
        return None, None, None

    lowered = text.lower()
    country: str | None = None
    region: str | None = None

    for keywords, c, r in _COUNTRY_RULES:
        if any(kw in lowered for kw in keywords):
            country = c
            region = r
            break

    # 简单拆分 "City, State/Region" 或 "City, Country"
    if "," in text and region is None:
        parts = [p.strip() for p in text.split(",")]
        # 如果第二部分是常见国家/地区缩写，视作 region
        if len(parts) == 2:
            region = parts[1]

    # 基于 region 做二次推断（如 CA -> United States）
    if country is None and region:
        region_lower = region.lower()
        if region_lower in {"ca", "california", "ny", "new york", "tx", "texas", "fl", "florida", "il", "illinois", "wa", "washington", "or", "oregon", "co", "colorado", "az", "arizona", "nv", "nevada", "ga", "georgia", "mi", "michigan", "pa", "pennsylvania", "oh", "ohio", "nc", "north carolina", "nj", "new jersey", "va", "virginia", "ma", "massachusetts", "tn", "tennessee", "in", "indiana", "mo", "missouri", "md", "maryland", "wi", "wisconsin", "mn", "minnesota", "al", "alabama", "sc", "south carolina", "la", "louisiana", "ky", "kentucky", "ok", "oklahoma", "ct", "connecticut", "ut", "utah", "ia", "iowa", "ar", "arkansas", "ms", "mississippi", "ks", "kansas", "nm", "new mexico", "ne", "nebraska", "wv", "west virginia", "id", "idaho", "hi", "hawaii", "nh", "new hampshire", "me", "maine", "mt", "montana", "ri", "rhode island", "de", "delaware", "sd", "south dakota", "nd", "north dakota", "ak", "alaska", "vt", "vermont", "wy", "wyoming"}:
            country = "United States"

    return country, region, text


def _extract_links(bio: str | None, website: str | None) -> tuple[list[str], list[str]]:
    """从 bio 中提取所有链接，并拆分为 website_links 与 merch_links。

    Returns (website_links, merch_links)
    """
    text = " ".join(filter(None, [bio or "", website or ""]))
    found = set()
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:!?")
        if not url.startswith("http"):
            url = "https://" + url
        found.add(url.lower())

    website_links = sorted(found)
    merch_links = [
        u for u in website_links
        if any(d in u for d in ("booth.pm", "etsy.com", "gumroad.com", "patreon.com", "shop", "store", "merch", "fanbox.cc", "ko-fi.com", "buymeacoffee.com", "vgen.co", "vgen.ai"))
    ]
    return website_links, merch_links


def _extract_email(bio: str | None) -> str | None:
    if not bio:
        return None
    match = _EMAIL_RE.search(bio)
    return match.group(0) if match else None


def _detect_commission_status(bio: str | None, website_links: list[str]) -> str | None:
    """推断接稿状态：open / closed / waitlist。"""
    if not bio:
        return None
    text = bio.lower()
    if any(k in text for k in ("commissions closed", "comm closed", "commissions: closed", "not accepting")):
        return "closed"
    if any(k in text for k in ("waitlist", "waiting list", "slot full", "queue full")):
        return "waitlist"
    if any(k in text for k in ("commissions open", "comm open", "commission open", "accepting commissions", "open for commission", "接稿", "依頼受付中")):
        return "open"
    # 如果 bio 只有 commission 关键词但没有 open/closed，模糊认为 open
    if "commission" in text:
        return "open"
    return None


def _extract_tags(bio: str | None, website: str | None, creator_type: str | None) -> tuple[list[str], list[str]]:
    """提取作品/业务标签与创作者类型标签。"""
    combined = " ".join(filter(None, [bio or "", website or ""])).lower()
    tags = set()
    for tag, keywords in _WORK_TAGS_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            tags.add(tag)

    type_tags = set()
    if creator_type and creator_type in _CREATOR_TYPE_TAGS:
        type_tags.add(_CREATOR_TYPE_TAGS[creator_type])

    return sorted(tags), sorted(type_tags)


def _build_social_links(website_links: list[str]) -> dict[str, Any]:
    """从链接列表中识别并归类社交平台。"""
    social: dict[str, list[str]] = {}
    for url in website_links:
        for domain, platform in _SOCIAL_DOMAINS.items():
            if domain in url:
                social.setdefault(platform, []).append(url)
                break
    # 去重并保持列表
    return {k: sorted(set(v)) for k, v in social.items()}


def _safe_jsonb(value: Any) -> str | None:
    """将任意对象转为 JSON 字符串，用于 raw_profile / social_links。"""
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None


def _calc_account_age_days(platform_created_at: datetime | str | None) -> int | None:
    """根据平台注册时间计算账号年龄（天）。"""
    if platform_created_at is None:
        return None
    try:
        if isinstance(platform_created_at, str):
            created = datetime.fromisoformat(platform_created_at.strip().replace("Z", "+00:00"))
        else:
            created = platform_created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).days
    except (ValueError, TypeError):
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    """安全解析时间戳字符串。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return None


def _is_eligible(creator_row: dict) -> bool:
    return bool(
        creator_row.get("is_seed")
        or creator_row.get("bd_decision") == "interested"
    )


def sync_creator_detail(
    creator_id: int,
    *,
    sync_source: str = "manual",
    raw_profile: dict[str, Any] | None = None,
) -> dict | None:
    """同步单个创作者到 creators_detail。

    如果该创作者不符合收录条件（非种子且 bd_decision != 'interested'），
    则删除已有的 detail 记录并返回 None。
    """
    creator = fetch_one("SELECT * FROM creators WHERE id = %s", (creator_id,))
    if not creator:
        logger.warning("Creator %d not found, skipping detail sync", creator_id)
        return None

    if not _is_eligible(creator):
        with get_cursor() as cur:
            cur.execute("DELETE FROM creators_detail WHERE creator_id = %s", (creator_id,))
        return None

    content_analysis = fetch_one(
        "SELECT is_realistic, has_fixed_ip FROM creator_content_analysis WHERE creator_id = %s AND status = 'completed' ORDER BY analyzed_at DESC LIMIT 1",
        (creator_id,),
    )

    bio = creator.get("bio") or ""
    website = creator.get("website") or ""
    creator_type = creator.get("creator_type_manual") or creator.get("creator_type_auto") or "unknown"

    location = raw_profile.get("location") if raw_profile else None
    country, region, parsed_location = _parse_location(location)

    # 如 raw_profile 有更准确的 country / timezone，优先使用
    if raw_profile:
        country = raw_profile.get("country") or country
        region = raw_profile.get("region") or region
        timezone_str = raw_profile.get("timeZone") or raw_profile.get("timezone")
    else:
        timezone_str = None

    followers = creator.get("followers")
    following = creator.get("following")
    tweets_count = creator.get("tweets_count")

    platform_created_at = _parse_timestamp(raw_profile.get("createdAt") if raw_profile else None)
    account_age_days = _calc_account_age_days(platform_created_at) or creator.get("account_age")

    website_links, merch_links = _extract_links(bio, website)
    email = _extract_email(bio)
    commission_status = _detect_commission_status(bio, website_links)
    tags, creator_type_tags = _extract_tags(bio, website, creator_type)

    # 内容风格分析结果补充标签
    if content_analysis:
        if content_analysis.get("is_realistic"):
            tags.append("Realistic")
        if content_analysis.get("has_fixed_ip"):
            tags.append("Fixed IP")

    social_links = _build_social_links(website_links)

    # 过滤排序去重
    tags = sorted(set(tags))
    creator_type_tags = sorted(set(creator_type_tags))

    # 从 raw_profile 获取更丰富字段
    display_name = raw_profile.get("displayName") or raw_profile.get("name") or raw_profile.get("screen_name") if raw_profile else None
    profile_image_url = raw_profile.get("profileImageUrl") or raw_profile.get("profile_image_url") or raw_profile.get("avatar") if raw_profile else None
    banner_image_url = raw_profile.get("bannerImageUrl") or raw_profile.get("banner_image_url") if raw_profile else None
    verified = raw_profile.get("verified") if raw_profile else None
    listed_count = raw_profile.get("listedCount") or raw_profile.get("listed_count") if raw_profile else None

    payload = {
        "creator_id": creator_id,
        "is_seed": creator.get("is_seed", False),
        "bd_decision": creator.get("bd_decision"),
        "display_name": display_name,
        "profile_image_url": profile_image_url,
        "banner_image_url": banner_image_url,
        "verified": verified,
        "location": parsed_location,
        "country": country,
        "region": region,
        "timezone": timezone_str,
        "followers": followers,
        "following": following,
        "tweets_count": tweets_count,
        "listed_count": listed_count,
        "account_age_days": account_age_days,
        "platform_created_at": platform_created_at,
        "tags": tags,
        "creator_type_tags": creator_type_tags,
        "website": website or None,
        "website_links": website_links,
        "email": email,
        "commission_status": commission_status,
        "merch_links": merch_links,
        "social_links": _safe_jsonb(social_links),
        "raw_profile": _safe_jsonb(raw_profile),
        "sync_source": sync_source,
    }

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO creators_detail (
                creator_id, is_seed, bd_decision, display_name, profile_image_url, banner_image_url,
                verified, location, country, region, timezone, followers, following, tweets_count,
                listed_count, account_age_days, platform_created_at, tags,
                creator_type_tags, website, website_links, email, commission_status, merch_links,
                social_links, raw_profile, sync_source, last_synced_at
            ) VALUES (
                %(creator_id)s, %(is_seed)s, %(bd_decision)s, %(display_name)s, %(profile_image_url)s, %(banner_image_url)s,
                %(verified)s, %(location)s, %(country)s, %(region)s, %(timezone)s, %(followers)s, %(following)s, %(tweets_count)s,
                %(listed_count)s, %(account_age_days)s, %(platform_created_at)s, %(tags)s,
                %(creator_type_tags)s, %(website)s, %(website_links)s, %(email)s, %(commission_status)s, %(merch_links)s,
                %(social_links)s, %(raw_profile)s, %(sync_source)s, NOW()
            )
            ON CONFLICT (creator_id) DO UPDATE SET
                is_seed = EXCLUDED.is_seed,
                bd_decision = EXCLUDED.bd_decision,
                display_name = COALESCE(EXCLUDED.display_name, creators_detail.display_name),
                profile_image_url = COALESCE(EXCLUDED.profile_image_url, creators_detail.profile_image_url),
                banner_image_url = COALESCE(EXCLUDED.banner_image_url, creators_detail.banner_image_url),
                verified = COALESCE(EXCLUDED.verified, creators_detail.verified),
                location = COALESCE(EXCLUDED.location, creators_detail.location),
                country = COALESCE(EXCLUDED.country, creators_detail.country),
                region = COALESCE(EXCLUDED.region, creators_detail.region),
                timezone = COALESCE(EXCLUDED.timezone, creators_detail.timezone),
                followers = COALESCE(EXCLUDED.followers, creators_detail.followers),
                following = COALESCE(EXCLUDED.following, creators_detail.following),
                tweets_count = COALESCE(EXCLUDED.tweets_count, creators_detail.tweets_count),
                listed_count = COALESCE(EXCLUDED.listed_count, creators_detail.listed_count),
                account_age_days = COALESCE(EXCLUDED.account_age_days, creators_detail.account_age_days),
                platform_created_at = COALESCE(EXCLUDED.platform_created_at, creators_detail.platform_created_at),
                tags = EXCLUDED.tags,
                creator_type_tags = EXCLUDED.creator_type_tags,
                website = COALESCE(EXCLUDED.website, creators_detail.website),
                website_links = COALESCE(EXCLUDED.website_links, creators_detail.website_links),
                email = COALESCE(EXCLUDED.email, creators_detail.email),
                commission_status = COALESCE(EXCLUDED.commission_status, creators_detail.commission_status),
                merch_links = COALESCE(EXCLUDED.merch_links, creators_detail.merch_links),
                social_links = COALESCE(EXCLUDED.social_links, creators_detail.social_links),
                raw_profile = COALESCE(EXCLUDED.raw_profile, creators_detail.raw_profile),
                sync_source = EXCLUDED.sync_source,
                last_synced_at = NOW()
            RETURNING id""",
            payload,
        )
        row = cur.fetchone()
        detail_id = row["id"] if row else None

    logger.info("Synced creator_detail id=%s creator_id=%s source=%s", detail_id, creator_id, sync_source)
    return {"detail_id": detail_id, "creator_id": creator_id, **payload}


def sync_all_eligible(
    limit: int | None = None,
    sync_source: str = "backfill",
) -> dict:
    """批量同步所有符合条件的创作者。

    Returns: {"total": int, "synced": int, "removed": int}
    """
    rows = fetch_all(
        """SELECT id FROM creators
           WHERE is_seed = true OR bd_decision = 'interested'
           ORDER BY first_seen_at ASC
           LIMIT %s""",
        (limit,) if limit else (None,),
    )
    synced = removed = 0
    for row in rows:
        result = sync_creator_detail(row["id"], sync_source=sync_source)
        if result:
            synced += 1
        else:
            removed += 1

    logger.info("Batch sync complete: synced=%d, removed=%d", synced, removed)
    return {"total": len(rows), "synced": synced, "removed": removed}


def remove_ineligible_detail(creator_id: int) -> bool:
    """手动移除不再符合条件的 detail 记录。"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM creators_detail WHERE creator_id = %s", (creator_id,))
        return cur.rowcount > 0
