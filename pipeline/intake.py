"""公共数据入库 + 规则/AI 过滤 — 供 webhook 和 discovery 同步模式共用。"""

import asyncio
import logging

from apify_client import ApifyClient

from db.connection import get_cursor

logger = logging.getLogger(__name__)


def store_dataset_items(items: list[dict]) -> dict:
    """Upsert Apify dataset items into creators table.

    Returns: {total, inserted, updated, usernames: set[str]}.
    """
    inserted = updated = 0
    usernames: set[str] = set()
    for item in items:
        username = (
            item.get("username") or item.get("screen_name")
            or item.get("userName") or ""
        )
        if not username:
            continue
        username = username.lstrip("@").lower()
        usernames.add(username)

        bio = item.get("description") or item.get("bio") or ""
        website = item.get("website") or item.get("url") or ""
        followers = item.get("followers") or item.get("followersCount") or 0
        following = item.get("following") or item.get("friendsCount") or 0
        tweets_count = item.get("statusesCount") or item.get("tweetsCount") or 0

        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO creators (username, bio, website, followers, following, tweets_count)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (username) DO UPDATE SET
                       bio = COALESCE(NULLIF(EXCLUDED.bio, ''), creators.bio),
                       website = COALESCE(NULLIF(EXCLUDED.website, ''), creators.website),
                       followers = EXCLUDED.followers,
                       following = EXCLUDED.following,
                       tweets_count = EXCLUDED.tweets_count
                   RETURNING (xmax = 0) AS is_insert""",
                (username, bio, website, followers, following, tweets_count),
            )
            row = cur.fetchone()
            if row and row["is_insert"]:
                inserted += 1
            else:
                updated += 1

    return {"total": len(items), "inserted": inserted, "updated": updated, "usernames": usernames}


def run_filter_pipeline(usernames: set[str] | None = None) -> dict:
    """Run rule filter (L1/L2) + AI filter (L3) on pending creators.

    If *usernames* is provided, only processes those users (scoped to current batch).
    Otherwise falls back to all pending creators (backward-compatible).

    Returns: {rule_passed, rule_rejected, ai_passed, ai_rejected, grey_zone}.
    """
    from pipeline.bio_rule_filter import BioRuleFilter
    from pipeline.ai_filter import AIFilter

    rule_filter = BioRuleFilter()
    ai_filter = AIFilter()

    if usernames:
        placeholders = ",".join(["%s"] * len(usernames))
        query = f"""SELECT id, bio, website FROM creators
                    WHERE bd_status = 'pending' AND bio IS NOT NULL AND bio != ''
                      AND username IN ({placeholders})"""
        with get_cursor() as cur:
            cur.execute(query, tuple(usernames))
            candidates = cur.fetchall()
    else:
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, bio, website FROM creators WHERE bd_status = 'pending' AND bio IS NOT NULL AND bio != ''"
            )
            candidates = cur.fetchall()

    stats = {"rule_passed": 0, "rule_rejected": 0, "ai_passed": 0, "ai_rejected": 0, "grey_zone": 0}
    grey_zone = []

    for c in candidates:
        result = rule_filter.filter(c["bio"], c.get("website") or "")
        if result["passed"] is True:
            with get_cursor() as cur:
                cur.execute("UPDATE creators SET bd_status = 'rule_passed' WHERE id = %s", (c["id"],))
            stats["rule_passed"] += 1
        elif result["passed"] is False:
            with get_cursor() as cur:
                cur.execute("UPDATE creators SET bd_status = 'rule_rejected' WHERE id = %s", (c["id"],))
            stats["rule_rejected"] += 1
        else:
            grey_zone.append(c)

    if grey_zone:
        stats["grey_zone"] = len(grey_zone)
        bio_batch = [{"id": c["id"], "bio": c["bio"]} for c in grey_zone]
        loop = asyncio.new_event_loop()
        try:
            ai_results = loop.run_until_complete(ai_filter.filter_batch(bio_batch))
        finally:
            loop.close()

        for r in ai_results:
            status = "ai_passed" if r.get("result") == "YES" else "ai_rejected"
            with get_cursor() as cur:
                cur.execute("UPDATE creators SET bd_status = %s WHERE id = %s", (status, r["bio_id"]))
            if status == "ai_passed":
                stats["ai_passed"] += 1
            else:
                stats["ai_rejected"] += 1

    logger.info("Filter pipeline: %s", stats)
    return stats


def process_dataset(client: ApifyClient, dataset_id: str) -> dict:
    """Fetch dataset from Apify, store items, and run filter pipeline.

    Convenience wrapper used by both webhook and discovery sync mode.
    """
    items = list(client.dataset(dataset_id).iterate_items())
    logger.info("Fetched %d items from dataset %s", len(items), dataset_id)

    store_stats = store_dataset_items(items)
    usernames = store_stats.pop("usernames", set())
    logger.info("Stored: %s", store_stats)

    filter_stats = run_filter_pipeline(usernames=usernames)
    return {"store": store_stats, "filter": filter_stats}
