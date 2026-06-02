"""定期粉丝刷新 — 使用 following_actor 为种子和 interested 创作者每3天刷新粉丝量。

查询结果同时更新 creators.followers 和 snapshot 表。
"""

import logging

import yaml
from apify_client import ApifyClient

from config.settings import (
    APIFY_API_TOKEN,
    APIFY_BUDGET_HARD_LIMIT,
    APIFY_CONFIG_PATH,
    DAILY_APIFY_BUDGET_USD,
    FOLLOWER_REFRESH_BATCH_SIZE,
    FOLLOWER_REFRESH_INTERVAL_DAYS,
)
from db.connection import fetch_all, fetch_one, get_cursor
from pipeline.growth_monitor import record_snapshot

logger = logging.getLogger(__name__)


def _get_refresh_candidates(limit: int = FOLLOWER_REFRESH_BATCH_SIZE) -> list[dict]:
    """Fetch creators that need periodic follower refresh.

    Rules:
      - is_seed = true  OR  bd_decision = 'interested'
      - NOT bd_decision IN ('rejected_unfit', 'rejected_not_creator')
      - last_follower_refresh_at is NULL or older than interval days
    """
    return fetch_all(
        """
        SELECT id, username, is_seed
        FROM creators
        WHERE (
            is_seed = true
            OR bd_decision = 'interested'
        )
          AND (last_follower_refresh_at IS NULL
               OR last_follower_refresh_at < NOW() - INTERVAL '%s days')
        ORDER BY last_follower_refresh_at ASC NULLS FIRST
        LIMIT %s
        """,
        (FOLLOWER_REFRESH_INTERVAL_DAYS, limit),
    )


def _check_budget() -> bool:
    """Check daily budget."""
    row = fetch_one(
        "SELECT COALESCE(SUM(apify_cost_usd), 0) AS today FROM cost_tracking WHERE date = CURRENT_DATE"
    )
    today = float(row["today"]) if row else 0.0
    if today >= DAILY_APIFY_BUDGET_USD:
        if APIFY_BUDGET_HARD_LIMIT:
            logger.warning(
                "Daily Apify budget exceeded ($%.2f) — blocking follower refresh", today
            )
            return False
        logger.warning(
            "Daily Apify budget exceeded ($%.2f) — continuing anyway", today
        )
    return True


def _store_follower_refresh_results(items: list[dict]) -> dict:
    """Parse following_actor results and update creators + snapshots."""
    updated = 0
    for item in items:
        author = item.get("author") or item
        username = (
            (author.get("userName") or author.get("username") or "").lstrip("@").lower()
            or (item.get("userName") or item.get("username") or "").lstrip("@").lower()
        )
        if not username:
            continue

        followers = author.get("followers") or author.get("followersCount") or 0
        following = author.get("following") or author.get("friendsCount") or 0
        tweets_count = author.get("statusesCount") or author.get("tweetsCount") or 0

        with get_cursor() as cur:
            cur.execute(
                """UPDATE creators SET
                       followers = COALESCE(%s, followers),
                       following = COALESCE(%s, following),
                       tweets_count = COALESCE(%s, tweets_count),
                       last_follower_refresh_at = NOW()
                   WHERE username = %s
                   RETURNING id, is_seed""",
                (followers, following, tweets_count, username),
            )
            row = cur.fetchone()
            if not row:
                continue
            creator_id = row["id"]
            is_seed = row.get("is_seed")
            updated += 1

        # Snapshot 写入（独立事务，幂等兜底）
        record_snapshot(
            creator_id=creator_id,
            followers=followers,
            following=following,
            tweets_count=tweets_count,
            source="follower_refresh",
            is_seed=bool(is_seed),
        )

    return {"updated": updated}


def run_follower_refresh() -> dict:
    """Trigger following_actor for candidates and store results.

    Returns: {"candidates": int, "run_id": str|None, "budget_ok": bool, "updated": int}
    """
    if not _check_budget():
        return {"candidates": 0, "run_id": None, "budget_ok": False, "updated": 0}

    candidates = _get_refresh_candidates()
    if not candidates:
        logger.info("No candidates pending follower refresh")
        return {"candidates": 0, "run_id": None, "budget_ok": True, "updated": 0}

    handles = [c["username"] for c in candidates]
    logger.info("Triggering follower refresh for %d candidates", len(handles))

    with open(APIFY_CONFIG_PATH, encoding="utf-8") as f:
        apify_cfg = yaml.safe_load(f)

    following_cfg = apify_cfg["following_actor"]
    actor_input = following_cfg["input"].copy()
    if "twitterHandles" in actor_input:
        actor_input["twitterHandles"] = handles
    else:
        actor_input["handles"] = handles
    # 覆盖参数：只获取 profile，不拉取 following/followers 列表
    actor_input["getFollowing"] = False
    actor_input["getFollowers"] = False
    actor_input["maxItems"] = len(handles) * 2  # 留少量余量

    client = ApifyClient(APIFY_API_TOKEN)
    run = client.actor(following_cfg["actor_id"]).call(run_input=actor_input)
    run_id = run.get("id", "")

    dataset_id = run.get("defaultDatasetId")
    stats = {"updated": 0}
    if dataset_id:
        items = list(client.dataset(dataset_id).iterate_items())
        stats = _store_follower_refresh_results(items)
        logger.info("Follower refresh complete: %s", stats)

    return {"candidates": len(candidates), "run_id": run_id, "budget_ok": True, **stats}
