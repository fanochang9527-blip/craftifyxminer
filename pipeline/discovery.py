"""每日发现引擎 — 动态锚点选择 + 10-20% 随机探索。

策略:
  80% 高价值 Seed (Tier S/A, 按 last_used_as_anchor 升序轮换)
  20% 随机探索 (跨地域 / 跨品类 / 时间随机)
"""

import logging
import random
from datetime import date, datetime

import yaml
from apify_client import ApifyClient

from config.settings import (
    APIFY_API_TOKEN,
    APIFY_CONFIG_PATH,
    DAILY_ANCHOR_COUNT,
    DAILY_APIFY_BUDGET_USD,
    EXPLORATION_RATIO,
    MAX_FOLLOWING_PER_ANCHOR,
)
from db.connection import execute, fetch_all, fetch_one, get_cursor

logger = logging.getLogger(__name__)

EXPLORE_HASHTAGS = {
    "geo_explore": [
        "#絵描きさんと繋がりたい",
        "#그림쟁이와_소통해요",
        "#ArtistOnTwitter",
    ],
    "hashtag_explore": [
        "#indiegame",
        "#gamedev",
        "#VTuber",
        "#plushie",
        "#enamelpin",
    ],
}


def generate_daily_seeds() -> list[dict]:
    """Return a list of anchor dicts: {username, strategy, seed_id}."""
    total = DAILY_ANCHOR_COUNT
    explore_count = max(1, int(total * EXPLORATION_RATIO))
    regular_count = total - explore_count

    # Regular: top-tier seeds rotated by last usage
    regular_seeds = fetch_all(
        """SELECT id, username FROM creators
           WHERE is_seed = true AND seed_tier IN ('S', 'A')
           ORDER BY COALESCE(
               (SELECT MAX(created_at) FROM discovery_batches
                WHERE %s = ANY(anchor_seeds)), '1970-01-01') ASC
           LIMIT %s""",
        (None, regular_count),  # placeholder – simplified rotation
    )

    # Fallback: if not enough S/A seeds, include B
    if len(regular_seeds) < regular_count:
        extra = fetch_all(
            """SELECT id, username FROM creators
               WHERE is_seed = true AND seed_tier = 'B'
               ORDER BY RANDOM() LIMIT %s""",
            (regular_count - len(regular_seeds),),
        )
        regular_seeds.extend(extra)

    anchors = [
        {"username": s["username"], "strategy": "seed_following", "seed_id": s["id"]}
        for s in regular_seeds
    ]

    # Exploration: pick from three strategies
    explore_seeds = _pick_exploration_anchors(explore_count)
    anchors.extend(explore_seeds)

    # Record batch
    usernames = [a["username"] for a in anchors]
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO discovery_batches
                   (batch_date, batch_type, anchor_seeds, exploration_ratio, raw_discovered)
               VALUES (%s, 'daily_l1', %s, %s, 0)""",
            (date.today(), usernames, EXPLORATION_RATIO),
        )

    logger.info("Generated %d anchors (%d regular + %d explore)", len(anchors), len(regular_seeds), len(explore_seeds))
    return anchors


def _pick_exploration_anchors(count: int) -> list[dict]:
    """Select exploration anchors using geo/hashtag/time strategies."""
    strategies = ["geo_explore", "hashtag_explore", "time_explore"]
    anchors: list[dict] = []

    for i in range(count):
        strategy = strategies[i % len(strategies)]

        if strategy == "time_explore":
            row = fetch_one(
                """SELECT id, username FROM creators
                   WHERE is_seed = true
                   ORDER BY RANDOM() LIMIT 1"""
            )
            if row:
                anchors.append({
                    "username": row["username"],
                    "strategy": strategy,
                    "seed_id": row["id"],
                })
        else:
            tags = EXPLORE_HASHTAGS.get(strategy, [])
            tag = random.choice(tags) if tags else "#art"
            anchors.append({
                "username": tag,
                "strategy": strategy,
                "seed_id": None,
            })

    return anchors


def trigger_l1_scan(anchors: list[dict] | None = None) -> dict:
    """Trigger Apify Following Actor for the given anchor list.

    Returns: {"runs_started": int, "budget_ok": bool}
    """
    if anchors is None:
        anchors = generate_daily_seeds()

    # Cost guard
    cost_row = fetch_one(
        "SELECT COALESCE(SUM(apify_cost_usd), 0) AS today_cost FROM cost_tracking WHERE date = CURRENT_DATE"
    )
    today_cost = float(cost_row["today_cost"]) if cost_row else 0.0
    if today_cost >= DAILY_APIFY_BUDGET_USD:
        logger.warning("Daily Apify budget exhausted ($%.2f >= $%.2f)", today_cost, DAILY_APIFY_BUDGET_USD)
        return {"runs_started": 0, "budget_ok": False}

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

    base_input["handles"] = handles
    base_input["max_items"] = MAX_FOLLOWING_PER_ANCHOR

    run = client.actor(actor_id).call(run_input=base_input)
    logger.info("Apify run started: %s", run.get("id"))

    return {"runs_started": 1, "budget_ok": True, "run_id": run.get("id")}
