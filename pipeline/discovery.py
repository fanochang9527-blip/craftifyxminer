"""每日发现引擎 — 全量种子锚点 + L1 扫描。

选取所有 is_seed=true 的种子，按 last_used_as_anchor 轮换爬取其 following 列表。
"""

import logging
from datetime import date

import yaml
from apify_client import ApifyClient

from config.settings import (
    APIFY_API_TOKEN,
    APIFY_CONFIG_PATH,
    DAILY_APIFY_BUDGET_USD,
    MAX_FOLLOWING_PER_ANCHOR,
)
from db.connection import execute, fetch_all, fetch_one, get_cursor

logger = logging.getLogger(__name__)


def generate_daily_seeds() -> list[dict]:
    """Return a list of anchor dicts for ALL seeds + BD-passed creators, rotated by last usage."""
    rows = fetch_all(
        """SELECT id, username, is_seed,
                  COALESCE(
                      (SELECT MAX(created_at) FROM discovery_batches
                       WHERE username = ANY(anchor_seeds)), '1970-01-01'
                  ) AS last_used
           FROM creators
           WHERE is_seed = true
              OR (is_seed = false AND bd_status IN ('interested', 'rejected_unfit'))
           ORDER BY last_used ASC"""
    )

    anchors = [
        {
            "username": r["username"],
            "strategy": "seed_following" if r["is_seed"] else "bd_following",
            "seed_id": r["id"],
        }
        for r in rows
    ]

    usernames = [a["username"] for a in anchors]
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO discovery_batches
                   (batch_date, batch_type, anchor_seeds, exploration_ratio, raw_discovered)
               VALUES (%s, 'daily_l1', %s, 0, 0)""",
            (date.today(), usernames),
        )

    seed_cnt = sum(1 for a in anchors if a["strategy"] == "seed_following")
    passed_cnt = len(anchors) - seed_cnt
    logger.info("Generated %d anchors (%d seeds + %d passed creators)", len(anchors), seed_cnt, passed_cnt)
    return anchors


def trigger_l1_scan(
    anchors: list[dict] | None = None,
    max_following: int | None = None,
) -> dict:
    """Trigger Apify Following Actor for the given anchor list.

    max_following: 覆盖环境变量 MAX_FOLLOWING_PER_ANCHOR（冒烟时可传 30–50）。

    Returns: {"runs_started": int, "budget_ok": bool, ...}
    """
    if anchors is None:
        anchors = generate_daily_seeds()

    cost_row = fetch_one(
        "SELECT COALESCE(SUM(apify_cost_usd), 0) AS today_cost FROM cost_tracking WHERE date = CURRENT_DATE"
    )
    today_cost = float(cost_row["today_cost"]) if cost_row else 0.0
    if today_cost >= DAILY_APIFY_BUDGET_USD:
        logger.warning("Daily Apify budget exceeded ($%.2f >= $%.2f) — continuing anyway", today_cost, DAILY_APIFY_BUDGET_USD)

    with open(APIFY_CONFIG_PATH, encoding="utf-8") as f:
        apify_cfg = yaml.safe_load(f)

    following_cfg = apify_cfg["following_actor"]
    actor_id = following_cfg["actor_id"]
    base_input = following_cfg["input"].copy()

    client = ApifyClient(APIFY_API_TOKEN)
    handles = [a["username"] for a in anchors if not a["username"].startswith("#")]

    if not handles:
        logger.info("No valid handles to scan")
        return {"runs_started": 0, "budget_ok": True}

    if "twitterHandles" in base_input:
        base_input["twitterHandles"] = handles
    else:
        base_input["handles"] = handles
    cap = max_following if max_following is not None else MAX_FOLLOWING_PER_ANCHOR
    if "maxItems" in base_input:
        base_input["maxItems"] = cap
    elif "max_items" in base_input:
        base_input["max_items"] = cap

    run = client.actor(actor_id).call(run_input=base_input)
    run_id = run.get("id", "")
    logger.info("Apify run completed: %s", run_id)

    dataset_id = run.get("defaultDatasetId")
    stored = {}
    if dataset_id:
        from pipeline.intake import process_dataset, tag_discovery_source
        stored = process_dataset(client, dataset_id)
        logger.info("L1 results processed: %s", stored)

        # 更新 discovery_batches 计数（raw_discovered / after_ai_filter）
        store_stats = stored.get("store", {})
        filter_stats = stored.get("filter", {})
        with get_cursor() as cur:
            cur.execute(
                """UPDATE discovery_batches
                   SET raw_discovered = %s,
                       after_ai_filter = %s
                   WHERE id = (
                       SELECT id FROM discovery_batches
                       WHERE batch_date = CURRENT_DATE
                       ORDER BY created_at DESC LIMIT 1
                   )""",
                (
                    store_stats.get("total", 0),
                    filter_stats.get("rule_passed", 0) + filter_stats.get("ai_passed", 0),
                ),
            )

        new_usernames = stored.get("store", {}).get("usernames", set())
        if not new_usernames:
            all_usernames = set()
            for item in client.dataset(dataset_id).iterate_items():
                u = (item.get("username") or item.get("screen_name")
                     or item.get("userName") or "")
                if u:
                    all_usernames.add(u.lstrip("@").lower())
            new_usernames = all_usernames

        _tag_batch(anchors, new_usernames, run_id)

    return {"runs_started": 1, "budget_ok": True, "run_id": run_id, "stored": stored}


def _tag_batch(anchors: list[dict], usernames: set[str], run_id: str) -> None:
    """Tag newly discovered creators with strategy/anchor from this batch."""
    from collections import Counter
    from pipeline.intake import tag_discovery_source

    strategies = Counter(a["strategy"] for a in anchors if not a["username"].startswith("#"))
    primary_strategy = strategies.most_common(1)[0][0] if strategies else "seed_following"

    seed_handles = [a["username"] for a in anchors if not a["username"].startswith("#")]
    anchor_label = ", ".join(f"@{h}" for h in seed_handles[:5])
    if len(seed_handles) > 5:
        anchor_label += f" (+{len(seed_handles) - 5})"

    tag_discovery_source(
        usernames=usernames,
        strategy=primary_strategy,
        anchor_seed=anchor_label,
        discovered_via=f"l1_batch:{run_id}",
    )
