"""深度抓取触发 — AI 过滤通过的候选人, 使用 Residential Proxy 抓取完整 Profile + Tweets。

批量触发 Apify Deep Scrape Actor (每批 50 人), 数据回写 creators + tweets 表。
"""

import logging
from datetime import date

import yaml
from apify_client import ApifyClient

from config.settings import (
    APIFY_API_TOKEN,
    APIFY_BUDGET_HARD_LIMIT,
    APIFY_CONFIG_PATH,
    APIFY_L2_ACTOR,
    DAILY_APIFY_BUDGET_USD,
    DEEP_SCRAPE_BATCH_SIZE,
)
from db.connection import fetch_all, fetch_one, get_cursor, upsert_cost
from pipeline.creator_detail_sync import sync_creator_detail

logger = logging.getLogger(__name__)


def _get_pending_candidates(limit: int = DEEP_SCRAPE_BATCH_SIZE) -> list[dict]:
    """Fetch creators that passed AI filter but haven't been deep-scraped in the last 30 days.

    当天新发现的候选人优先处理，避免 backlog 无限积压。
    """
    return fetch_all(
        """SELECT id, username FROM creators
           WHERE bd_status IN ('rule_passed', 'ai_passed')
             AND id NOT IN (
                 SELECT DISTINCT creator_id FROM tweets
                 WHERE creator_id IS NOT NULL
                   AND collected_at > NOW() - INTERVAL '30 days'
             )
           ORDER BY
               CASE WHEN discovered_date = CURRENT_DATE THEN 0 ELSE 1 END ASC,
               first_seen_at ASC
           LIMIT %s""",
        (limit,),
    )


def _check_budget() -> bool:
    """Check daily budget. 若 APIFY_BUDGET_HARD_LIMIT=true 则阻断，否则仅警告。"""
    row = fetch_one(
        "SELECT COALESCE(SUM(apify_cost_usd), 0) AS today FROM cost_tracking WHERE date = CURRENT_DATE"
    )
    today = float(row["today"]) if row else 0.0
    if today >= DAILY_APIFY_BUDGET_USD:
        if APIFY_BUDGET_HARD_LIMIT:
            logger.warning("Daily Apify budget exceeded ($%.2f) — blocking pipeline", today)
            return False
        logger.warning("Daily Apify budget exceeded ($%.2f) — continuing anyway", today)
    return True


def _store_deep_scrape_results(items: list[dict]) -> dict:
    """Parse apidojo/tweet-scraper results (each item = one tweet) into creators + tweets.

    Groups tweets by author, updates creator profile once per author, then inserts tweets.
    """
    from collections import defaultdict

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

    profiles_updated = tweets_inserted = 0

    synced_creator_profiles: dict[int, dict] = {}

    for username, tweets in by_author.items():
        author = author_info[username]
        with get_cursor() as cur:
            cur.execute(
                """UPDATE creators SET
                       followers = COALESCE(%s, followers),
                       following = COALESCE(%s, following)
                   WHERE username = %s
                   RETURNING id""",
                (
                    author.get("followers") or author.get("followersCount"),
                    author.get("following") or author.get("friendsCount"),
                    username,
                ),
            )
            row = cur.fetchone()
            if not row:
                continue
            creator_id = row["id"]
            profiles_updated += 1
            synced_creator_profiles[creator_id] = author

            # 追加：记录 snapshot（同一事务）
            cur.execute(
                "SELECT is_seed, bd_decision FROM creators WHERE id = %s",
                (creator_id,),
            )
            creator_row = cur.fetchone()
            is_seed = creator_row and creator_row.get("is_seed")
            table = "seed_follower_snapshots" if is_seed else "creator_snapshots"
            author_tweets_count = (
                author.get("statusesCount") or author.get("tweetsCount") or 0
            )
            cur.execute(
                f"""
                INSERT INTO {table} (creator_id, observed_at, followers, following, tweets_count, source)
                VALUES (%s, DATE_TRUNC('day', NOW()), %s, %s, %s, 'deep_scrape')
                ON CONFLICT (creator_id, observed_at) DO UPDATE SET
                    followers = EXCLUDED.followers,
                    following = EXCLUDED.following,
                    tweets_count = EXCLUDED.tweets_count,
                    source = EXCLUDED.source
                """,
                (
                    creator_id,
                    author.get("followers") or author.get("followersCount") or 0,
                    author.get("following") or author.get("friendsCount") or 0,
                    author_tweets_count,
                ),
            )

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
                tweets_inserted += 1

    # 同步高价值创作者详情档案（种子或 BD interested）
    for cid, author in synced_creator_profiles.items():
        try:
            sync_creator_detail(cid, sync_source="deep_scrape", raw_profile=author)
        except Exception:
            logger.exception("Failed to sync creator_detail for creator %d", cid)

    return {"profiles_updated": profiles_updated, "tweets_inserted": tweets_inserted}


def _log_daily_consumption_alert() -> None:
    """检查当天新发现的 passed 候选人消费率，未消费完时打印预警。"""
    row = fetch_one(
        """SELECT
               COUNT(*) FILTER (WHERE bd_status IN ('rule_passed','ai_passed')) AS total_passed,
               COUNT(*) FILTER (
                   WHERE bd_status IN ('rule_passed','ai_passed')
                     AND EXISTS (SELECT 1 FROM tweets t WHERE t.creator_id = creators.id)
               ) AS deep_scraped
           FROM creators
           WHERE discovered_date = CURRENT_DATE"""
    )
    if not row:
        return
    total_passed = int(row["total_passed"] or 0)
    deep_scraped = int(row["deep_scraped"] or 0)
    if total_passed > 0:
        rate = deep_scraped / total_passed
        if rate < 1.0:
            logger.warning(
                "DAILY_CONSUMPTION_ALERT: %d/%d (%.1f%%) of today's passed creators have been deep-scraped. "
                "Consider increasing DEEP_SCRAPE_BATCH_SIZE (currently %d).",
                deep_scraped, total_passed, rate * 100, DEEP_SCRAPE_BATCH_SIZE,
            )
        else:
            logger.info(
                "Daily consumption OK: %d/%d (100%%) today's passed creators deep-scraped.",
                deep_scraped, total_passed,
            )


def trigger_deep_scrape_batch(limit: int | None = None) -> dict:
    """Trigger deep-scrape for the next batch of filtered candidates.

    Returns: {"candidates": int, "run_id": str|None, "budget_ok": bool}
    """
    if limit is None:
        limit = DEEP_SCRAPE_BATCH_SIZE
    if not _check_budget():
        return {"candidates": 0, "run_id": None, "budget_ok": False}

    candidates = _get_pending_candidates(limit)
    if not candidates:
        logger.info("No candidates pending deep scrape")
        return {"candidates": 0, "run_id": None, "budget_ok": True}

    handles = [c["username"] for c in candidates]
    logger.info("Triggering deep scrape for %d candidates", len(handles))

    with open(APIFY_CONFIG_PATH, encoding="utf-8") as f:
        apify_cfg = yaml.safe_load(f)

    cfg_key = "alt_profile_actor" if APIFY_L2_ACTOR == "alt" else "profile_actor"
    profile_cfg = apify_cfg[cfg_key]
    actor_input = profile_cfg["input"].copy()
    for key in ("twitterHandles", "usernames", "handles"):
        if key in actor_input:
            actor_input[key] = handles
            break

    # apidojo tweet-scraper 的 maxItems 是全局计数，需要乘 handles 数；
    # 备选 Actor 的 maxResults 多为 per-user 语义，直接信任配置值
    if "apidojo" in profile_cfg.get("actor_id", ""):
        tweets_per_handle = 10
        actor_input["maxItems"] = max(actor_input.get("maxItems", 500), len(handles) * tweets_per_handle)

    client = ApifyClient(APIFY_API_TOKEN)
    run = client.actor(profile_cfg["actor_id"]).call(run_input=actor_input)
    run_id = run.get("id", "")
    usage_usd = float(run.get("usageTotalUsd") or 0.0)
    if usage_usd > 0:
        upsert_cost(date.today(), apify_cost_usd=usage_usd)

    # Fetch results immediately (synchronous call waits for completion)
    dataset_id = run.get("defaultDatasetId")
    if dataset_id:
        items = list(client.dataset(dataset_id).iterate_items())
        stats = _store_deep_scrape_results(items)
        logger.info("Deep scrape complete: %s", stats)

        with get_cursor() as cur:
            cur.execute(
                """UPDATE discovery_batches
                   SET after_deep_scrape = after_deep_scrape + %s
                   WHERE id = (
                       SELECT id FROM discovery_batches
                       WHERE batch_date = CURRENT_DATE
                       ORDER BY created_at DESC LIMIT 1
                   )""",
                (stats["profiles_updated"],),
            )

    _log_daily_consumption_alert()
    return {"candidates": len(candidates), "run_id": run_id, "budget_ok": True}


def trigger_seed_deep_scrape(usernames: list[str]) -> dict:
    """Deep-scrape specific seed users — ignores budget limits.

    Called by seed_import to ensure seeds always have full profile + tweet data.
    """
    if not usernames:
        return {"candidates": 0, "run_id": None}

    logger.info("Triggering seed deep scrape for %d users", len(usernames))

    with open(APIFY_CONFIG_PATH, encoding="utf-8") as f:
        apify_cfg = yaml.safe_load(f)

    cfg_key = "alt_profile_actor" if APIFY_L2_ACTOR == "alt" else "profile_actor"
    profile_cfg = apify_cfg[cfg_key]
    actor_input = profile_cfg["input"].copy()
    for key in ("twitterHandles", "usernames", "handles"):
        if key in actor_input:
            actor_input[key] = usernames
            break

    if "apidojo" in profile_cfg.get("actor_id", ""):
        tweets_per_handle = 10
        actor_input["maxItems"] = max(actor_input.get("maxItems", 500), len(usernames) * tweets_per_handle)

    client = ApifyClient(APIFY_API_TOKEN)
    run = client.actor(profile_cfg["actor_id"]).call(run_input=actor_input)
    run_id = run.get("id", "")
    usage_usd = float(run.get("usageTotalUsd") or 0.0)
    if usage_usd > 0:
        upsert_cost(date.today(), apify_cost_usd=usage_usd)

    dataset_id = run.get("defaultDatasetId")
    stats = {}
    if dataset_id:
        items = list(client.dataset(dataset_id).iterate_items())
        stats = _store_deep_scrape_results(items)
        logger.info("Seed deep scrape complete: %s", stats)

    return {"candidates": len(usernames), "run_id": run_id, **stats}
