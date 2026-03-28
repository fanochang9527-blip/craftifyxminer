"""深度抓取触发 — AI 过滤通过的候选人, 使用 Residential Proxy 抓取完整 Profile + Tweets。

批量触发 Apify Deep Scrape Actor (每批 50 人), 数据回写 creators + tweets 表。
"""

import logging
from datetime import date

import yaml
from apify_client import ApifyClient

from config.settings import (
    APIFY_API_TOKEN,
    APIFY_CONFIG_PATH,
    DAILY_APIFY_BUDGET_USD,
    DEEP_SCRAPE_BATCH_SIZE,
)
from db.connection import fetch_all, fetch_one, get_cursor, upsert_cost

logger = logging.getLogger(__name__)


def _get_pending_candidates(limit: int = DEEP_SCRAPE_BATCH_SIZE) -> list[dict]:
    """Fetch creators that passed AI filter but haven't been deep-scraped yet."""
    return fetch_all(
        """SELECT id, username FROM creators
           WHERE bd_status IN ('rule_passed', 'ai_passed')
             AND id NOT IN (SELECT DISTINCT creator_id FROM tweets WHERE creator_id IS NOT NULL)
           ORDER BY first_seen_at ASC
           LIMIT %s""",
        (limit,),
    )


def _check_budget() -> bool:
    row = fetch_one(
        "SELECT COALESCE(SUM(apify_cost_usd), 0) AS today FROM cost_tracking WHERE date = CURRENT_DATE"
    )
    today = float(row["today"]) if row else 0.0
    if today >= DAILY_APIFY_BUDGET_USD:
        logger.warning("Daily Apify budget exhausted ($%.2f)", today)
        return False
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

        for tw in tweets:
            tweet_id = str(tw.get("id") or tw.get("id_str") or "")
            if not tweet_id:
                continue

            media: list[str] = []
            for m in tw.get("extendedEntities", {}).get("media", []):
                url = m.get("media_url_https") or m.get("media_url") or ""
                if url:
                    media.append(url)

            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO tweets
                           (tweet_id, creator_id, likes, retweets, replies, views,
                            created_at, text, media_urls)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        media or [],
                    ),
                )
                tweets_inserted += 1

    return {"profiles_updated": profiles_updated, "tweets_inserted": tweets_inserted}


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

    profile_cfg = apify_cfg["profile_actor"]
    actor_input = profile_cfg["input"].copy()
    if "twitterHandles" in actor_input:
        actor_input["twitterHandles"] = handles
    else:
        actor_input["handles"] = handles
    tweets_per_handle = 10
    actor_input["maxItems"] = max(actor_input.get("maxItems", 500), len(handles) * tweets_per_handle)

    client = ApifyClient(APIFY_API_TOKEN)
    run = client.actor(profile_cfg["actor_id"]).call(run_input=actor_input)
    run_id = run.get("id", "")

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

    return {"candidates": len(candidates), "run_id": run_id, "budget_ok": True}
