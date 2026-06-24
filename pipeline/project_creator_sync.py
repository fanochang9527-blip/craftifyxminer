"""项目级作者信息同步：通过 X 链接调用 Apify 抓取作者主页，补全 projects 表创作者特征。

流程：
1. 从 projects / 清洗后的 CSV 中收集需要采集的 X 链接。
2. 提取 handles，批量调用 Apify twitter-user-scraper 获取 profile。
3. 创建/更新 creators 表。
4. 从 profile 计算简化的 creator_features。
5. 将创作者特征回写到 projects 表对应行。

注意：这里使用的是简化版创作者特征（不跑 LLM、不深抓推文），以降低 Apify 成本。
"""

from __future__ import annotations

import logging
import math
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from apify_client import ApifyClient

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import (
    APIFY_API_TOKEN,
    APIFY_BUDGET_HARD_LIMIT,
    APIFY_CONFIG_PATH,
    DAILY_APIFY_BUDGET_USD,
)
from db.connection import fetch_all, fetch_one, get_cursor, upsert_cost

logger = logging.getLogger(__name__)

# 简单 NSFW 关键词
_NSFW_KEYWORDS = re.compile(
    r"\b(?:nsfw|adult|18\+|hentai|porn|nude|lewd|kink|fetish|erotic|sex|cum)\b",
    re.IGNORECASE,
)

# 店铺/ commerce 关键词
_SHOP_KEYWORDS = re.compile(
    r"\b(?:shop|store|etsy|booth|patreon|ko-fi|kofi| commissions?|merch|preorder|预购|通贩)\b",
    re.IGNORECASE,
)

# 内容分类关键词（简化规则）
_CONTENT_KEYWORDS = {
    "furry": re.compile(r"\b(?:furry|fursona|anthro)\b", re.IGNORECASE),
    "anime": re.compile(r"\b(?:anime|manga|二次元|动漫)\b", re.IGNORECASE),
    "vtuber": re.compile(r"\b(?:vtuber|vtubers|virtual youtuber|hololive|nijisanji)\b", re.IGNORECASE),
    "gaming": re.compile(r"\b(?:gaming|gamer|game|streamer|twitch)\b", re.IGNORECASE),
    "webcomic": re.compile(r"\b(?:webcomic|comic|webtoon|manga artist)\b", re.IGNORECASE),
    "bl": re.compile(r"\b(?:bl|boys? love|yaoi|shounen ai)\b", re.IGNORECASE),
    "gl": re.compile(r"\b(?:gl|girls? love|yuri)\b", re.IGNORECASE),
}


def _extract_handle_from_x_link(x_link: str) -> str | None:
    """从 https://x.com/username 或 https://twitter.com/username 中提取 username。"""
    if not x_link:
        return None
    try:
        parsed = urlsplit(x_link.strip())
        path = parsed.path.strip("/")
        if not path:
            return None
        handle = path.split("/")[0]
        handle = handle.split("?")[0].split("#")[0]
        handle = handle.lstrip("@").lower()
        return handle if handle else None
    except Exception:
        return None


def _parse_created_at(created_at) -> date | None:
    """把 Apify 返回的 created_at 字符串转成 date。"""
    if not created_at:
        return None
    if isinstance(created_at, date) and not isinstance(created_at, datetime):
        return created_at
    text = str(created_at)
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            from datetime import datetime

            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _account_age_days(created_at) -> int:
    """根据账号创建时间估算账号年龄（天）。"""
    created_date = _parse_created_at(created_at)
    if not created_date:
        return 0
    try:
        from datetime import datetime

        return (datetime.now().date() - created_date).days
    except Exception:
        return 0


def _compute_features_from_profile(item: dict, is_multi_platform: bool = False) -> dict:
    """从 Apify profile item 计算简化版 creator_features。"""
    author = item.get("author") or item

    followers = float(author.get("followers") or author.get("followersCount") or 0)
    following = float(author.get("following") or author.get("friendsCount") or 0)
    tweets_count = float(author.get("statusesCount") or author.get("tweetsCount") or 0)
    bio = str(author.get("description") or author.get("bio") or "")
    website = str(author.get("website") or "")
    created_at = author.get("createdAt") or author.get("created_at")
    account_age_days = _account_age_days(created_at)

    text_for_classification = f"{bio} {website}".lower()

    # 内容分类：基于 bio + website 关键词
    content_classes = [k for k, p in _CONTENT_KEYWORDS.items() if p.search(text_for_classification)]
    if not content_classes:
        content_classes = ["anime"]

    # market tier：简化按粉丝数分档
    if followers >= 100000:
        market_tier = "high"
    elif followers >= 10000:
        market_tier = "mid"
    else:
        market_tier = "low"

    return {
        "creator_followers": followers,
        "creator_following": following,
        "creator_tweets_count": tweets_count,
        "creator_bio": bio,
        "creator_followers_log": math.log1p(followers),
        "creator_following_follower_ratio": following / max(followers, 1),
        "creator_avg_daily_posts_30d": tweets_count / max(account_age_days, 1) * 30,
        "creator_reply_engagement_rate": 0.0,  # 无推文数据，无法计算
        "creator_account_age_days_log": math.log1p(max(account_age_days, 0)),
        "creator_has_shop_link": bool(_SHOP_KEYWORDS.search(text_for_classification) or website),
        "creator_is_nsfw": bool(_NSFW_KEYWORDS.search(text_for_classification)),
        "creator_is_multi_platform": is_multi_platform,
        "creator_market_tier_high": market_tier == "high",
        "creator_market_tier_mid": market_tier == "mid",
        "creator_market_tier_low": market_tier == "low",
        "creator_content_furry": "furry" in content_classes,
        "creator_content_anime": "anime" in content_classes,
        "creator_content_vtuber": "vtuber" in content_classes,
        "creator_content_gaming": "gaming" in content_classes,
        "creator_content_webcomic": "webcomic" in content_classes,
        "creator_content_bl": "bl" in content_classes,
        "creator_content_gl": "gl" in content_classes,
        "creator_content_nsfw": "nsfw" in content_classes,
    }


def _upsert_creator(author: dict) -> int | None:
    """把 Apify profile 写入 creators 表，返回 creator_id。"""
    username = (
        author.get("username") or author.get("userName") or author.get("screen_name") or ""
    ).lstrip("@").lower()
    if not username:
        return None

    bio = str(author.get("description") or author.get("bio") or "")
    website = str(author.get("website") or "")
    followers = author.get("followers") or author.get("followersCount") or 0
    following = author.get("following") or author.get("friendsCount") or 0
    tweets_count = author.get("statusesCount") or author.get("tweetsCount") or 0

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO creators (
                   username, bio, website, followers, following, tweets_count,
                   platform, platform_account_id)
               VALUES (%s, %s, %s, %s, %s, %s, 'twitter', %s)
               ON CONFLICT (platform, platform_account_id) DO UPDATE SET
                   username = EXCLUDED.username,
                   bio = COALESCE(NULLIF(EXCLUDED.bio, ''), creators.bio),
                   website = COALESCE(NULLIF(EXCLUDED.website, ''), creators.website),
                   followers = EXCLUDED.followers,
                   following = EXCLUDED.following,
                   tweets_count = EXCLUDED.tweets_count
               RETURNING id""",
            (username, bio, website, followers, following, tweets_count, username),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def _check_budget(n_handles: int) -> bool:
    """检查当日 Apify 预算，若 hard limit 开启且已超支则阻断。"""
    if not APIFY_API_TOKEN:
        logger.warning("APIFY_API_TOKEN not set, skipping Apify sync")
        return False

    row = fetch_one(
        "SELECT COALESCE(SUM(apify_cost_usd), 0) AS today FROM cost_tracking WHERE date = CURRENT_DATE"
    )
    today = float(row["today"]) if row else 0.0
    if today >= DAILY_APIFY_BUDGET_USD:
        if APIFY_BUDGET_HARD_LIMIT:
            logger.warning("Daily Apify budget exceeded ($%.2f) — blocking project creator sync", today)
            return False
        logger.warning("Daily Apify budget exceeded ($%.2f) — continuing anyway", today)
    return True


def fetch_creator_profiles(x_links: list[str]) -> dict[str, dict]:
    """批量调用 Apify 抓取 X 主页信息。

    Returns:
        {x_link: profile_item}
    """
    if not x_links:
        return {}

    if not _check_budget(len(x_links)):
        return {}

    handle_to_links: dict[str, list[str]] = {}
    for link in x_links:
        handle = _extract_handle_from_x_link(link)
        if handle:
            handle_to_links.setdefault(handle, []).append(link)

    handles = list(handle_to_links.keys())
    if not handles:
        logger.warning("No valid X handles to fetch")
        return {}

    logger.info("Fetching %d X profiles via Apify...", len(handles))

    # 读取 Apify 配置，使用 twitter-user-scraper 仅抓 profile
    with open(APIFY_CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    actor_id = cfg.get("following_actor", {}).get("actor_id", "apidojo/twitter-user-scraper")
    base_input = cfg.get("following_actor", {}).get("input", {})
    actor_input = dict(base_input)
    # 找到 handles 对应的 key
    for key in ("twitterHandles", "handles", "usernames"):
        if key in actor_input:
            actor_input[key] = handles
            break
    else:
        actor_input["twitterHandles"] = handles

    actor_input["getFollowing"] = False
    actor_input["getFollowers"] = False
    actor_input["maxItems"] = max(len(handles) * 5, 100)

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

    logger.info("Apify run %s: %d items, $%.4f", run_id, len(items), usage_usd)

    # 按 username 索引结果
    handle_to_item: dict[str, dict] = {}
    for item in items:
        author = item.get("author") or item
        username = (
            author.get("username") or author.get("userName") or author.get("screen_name") or ""
        ).lstrip("@").lower()
        if username:
            handle_to_item[username] = item

    # 映射回原始 x_link（同一 handle 可能对应多个 x_link/query）
    result: dict[str, dict] = {}
    for handle, links in handle_to_links.items():
        item = handle_to_item.get(handle)
        if item:
            for link in links:
                result[link] = item

    logger.info("Matched profiles for %d/%d x_links (%d unique handles)", len(result), len(x_links), len(handles))
    return result


def sync_project_creators(project_ids: list[str] | None = None) -> dict:
    """同步 projects 表中项目的创作者信息。

    Args:
        project_ids: 可选，只同步指定 project_id。为 None 时同步全部缺少 creator 特征的项目。

    Returns:
        {"total": int, "synced": int, "failed": int}
    """
    if project_ids:
        rows = fetch_all(
            """
            SELECT project_id, x_link, creator_is_multi_platform
            FROM projects
            WHERE project_id = ANY(%s) AND x_link IS NOT NULL
            """,
            (project_ids,),
        )
    else:
        rows = fetch_all(
            """
            SELECT project_id, x_link, creator_is_multi_platform
            FROM projects
            WHERE x_link IS NOT NULL
              AND creator_username IS NULL
            """
        )

    if not rows:
        logger.info("No projects need creator sync")
        return {"total": 0, "synced": 0, "failed": 0}

    x_link_to_infos: dict[str, list[tuple[str, bool]]] = {}
    for row in rows:
        x_link = row["x_link"]
        if x_link:
            x_link_to_infos.setdefault(x_link, []).append(
                (row["project_id"], row["creator_is_multi_platform"])
            )

    unique_x_links = list(x_link_to_infos.keys())
    profiles = fetch_creator_profiles(unique_x_links)

    synced = failed = 0
    for x_link, infos in x_link_to_infos.items():
        item = profiles.get(x_link)
        if not item:
            failed += len(infos)
            for project_id, _ in infos:
                logger.warning("No Apify profile for project %s x_link %s", project_id, x_link)
            continue

        author = item.get("author") or item
        creator_id = _upsert_creator(author)

        username = (
            author.get("username") or author.get("userName") or author.get("screen_name") or ""
        ).lstrip("@").lower()

        for project_id, is_multi_platform in infos:
            features = _compute_features_from_profile(item, is_multi_platform)

            with get_cursor() as cur:
                cur.execute(
                    """
                    UPDATE projects SET
                        creator_id = %s,
                        creator_username = %s,
                        creator_followers = %s,
                        creator_following = %s,
                        creator_tweets_count = %s,
                        creator_bio = %s,
                        creator_followers_log = %s,
                        creator_following_follower_ratio = %s,
                        creator_avg_daily_posts_30d = %s,
                        creator_reply_engagement_rate = %s,
                        creator_account_age_days_log = %s,
                        creator_has_shop_link = %s,
                        creator_is_nsfw = %s,
                        creator_is_multi_platform = %s,
                        creator_market_tier_high = %s,
                        creator_market_tier_mid = %s,
                        creator_market_tier_low = %s,
                        creator_content_furry = %s,
                        creator_content_anime = %s,
                        creator_content_vtuber = %s,
                        creator_content_gaming = %s,
                        creator_content_webcomic = %s,
                        creator_content_bl = %s,
                        creator_content_gl = %s,
                        creator_content_nsfw = %s,
                        updated_at = NOW()
                    WHERE project_id = %s
                    """,
                    (
                        creator_id,
                        username,
                        features["creator_followers"],
                        features["creator_following"],
                        features["creator_tweets_count"],
                        features["creator_bio"],
                        features["creator_followers_log"],
                        features["creator_following_follower_ratio"],
                        features["creator_avg_daily_posts_30d"],
                        features["creator_reply_engagement_rate"],
                        features["creator_account_age_days_log"],
                        features["creator_has_shop_link"],
                        features["creator_is_nsfw"],
                        features["creator_is_multi_platform"],
                        features["creator_market_tier_high"],
                        features["creator_market_tier_mid"],
                        features["creator_market_tier_low"],
                        features["creator_content_furry"],
                        features["creator_content_anime"],
                        features["creator_content_vtuber"],
                        features["creator_content_gaming"],
                        features["creator_content_webcomic"],
                        features["creator_content_bl"],
                        features["creator_content_gl"],
                        features["creator_content_nsfw"],
                        project_id,
                    ),
                )
            synced += 1

    logger.info("Project creator sync complete: total=%d, synced=%d, failed=%d", len(rows), synced, failed)
    return {"total": len(rows), "synced": synced, "failed": failed}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = sync_project_creators()
    print(
        f"Synced {result['synced']}/{result['total']} project creators, "
        f"failed {result['failed']}"
    )
