"""每日发现引擎 — 锚点轮换 + 冷却期 + 高价值优先。

按冷却期过滤已近期扫描过的锚点，优先选取高价值锚点，同价值按轮换顺序
（last_scraped_as_anchor 升序）排布，确保每个锚点长期内都能被照顾到。
"""

import logging
from datetime import date, datetime, timedelta, timezone

import yaml
from apify_client import ApifyClient

from config.settings import (
    ANCHOR_HIGH_VALUE_COOLDOWN_DAYS,
    ANCHOR_LOW_VALUE_COOLDOWN_DAYS,
    ANCHOR_NORMAL_COOLDOWN_DAYS,
    APIFY_API_TOKEN,
    APIFY_BUDGET_HARD_LIMIT,
    APIFY_CONFIG_PATH,
    APIFY_L1_ACTOR,
    DAILY_ANCHOR_COUNT,
    DAILY_APIFY_BUDGET_USD,
    MAX_FOLLOWING_PER_ANCHOR,
)
from db.connection import execute, fetch_all, fetch_one, get_cursor, upsert_cost

logger = logging.getLogger(__name__)


def _anchor_priority_and_cooldown(row: dict) -> tuple[int, int]:
    """Return (priority, cooldown_days) for an anchor row.

    Priority: higher number = picked first.
    """
    if row["is_seed"]:
        return 3, ANCHOR_HIGH_VALUE_COOLDOWN_DAYS
    if row["bd_status"] == "interested":
        return 2, ANCHOR_NORMAL_COOLDOWN_DAYS
    return 1, ANCHOR_LOW_VALUE_COOLDOWN_DAYS


def generate_daily_seeds() -> list[dict]:
    """Return anchor dicts with cooldown rotation and value-based priority.

    Rules:
      1. Cooldown: skip anchors scanned within their tier's cooldown window.
      2. Priority: is_seed (3) > interested (2) > rejected_unfit (1).
      3. Rotation: within same priority, pick least-recently-scanned first.
      4. Cap: at most DAILY_ANCHOR_COUNT anchors per day.
      5. Fallback: if cooldown leaves us short, relax cooldown and fill by
         last_scraped_as_anchor ASC (oldest first).
    """
    rows = fetch_all(
        """SELECT id, username, is_seed, bd_status, last_scraped_as_anchor
           FROM creators
           WHERE is_seed = true
              OR (is_seed = false AND bd_status IN ('interested', 'rejected_unfit'))"""
    )

    now = datetime.now(timezone.utc)

    # Decorate each row with priority and cooldown deadline
    decorated: list[tuple[int, datetime | None, dict]] = []
    for r in rows:
        priority, cooldown_days = _anchor_priority_and_cooldown(r)
        last_scraped = r["last_scraped_as_anchor"]
        # Treat naive datetimes as UTC to match PostgreSQL TIMESTAMP WITH TIME ZONE
        if last_scraped and last_scraped.tzinfo is None:
            last_scraped = last_scraped.replace(tzinfo=timezone.utc)
        deadline = last_scraped + timedelta(days=cooldown_days) if last_scraped else None
        decorated.append((priority, deadline, r))

    # Phase 1: pick anchors whose cooldown has expired (or never scraped)
    eligible = [d for d in decorated if d[1] is None or d[1] <= now]
    eligible.sort(key=lambda d: (-d[0], d[1] is not None, d[2]["last_scraped_as_anchor"] or datetime.min.replace(tzinfo=timezone.utc)))
    # Sort key explanation:
    #   -d[0]  -> higher priority first
    #   d[1] is not None -> put never-scraped (None) before scraped ones
    #   last_scraped_as_anchor ASC -> oldest first

    selected = eligible[:DAILY_ANCHOR_COUNT]

    # Phase 2: if still short, relax cooldown and fill from all candidates
    shortfall = DAILY_ANCHOR_COUNT - len(selected)
    if shortfall > 0:
        already_ids = {d[2]["id"] for d in selected}
        remaining = [d for d in decorated if d[2]["id"] not in already_ids]
        # Sort by priority desc, then last_scraped_as_anchor asc (oldest first, None first)
        remaining.sort(key=lambda d: (-d[0], d[2]["last_scraped_as_anchor"] is not None, d[2]["last_scraped_as_anchor"] or datetime.min.replace(tzinfo=timezone.utc)))
        selected.extend(remaining[:shortfall])

    anchors = [
        {
            "username": d[2]["username"],
            "strategy": "seed_following" if d[2]["is_seed"] else "bd_following",
            "seed_id": d[2]["id"],
        }
        for d in selected
    ]

    # Persist rotation state
    anchor_ids = [d[2]["id"] for d in selected]
    usernames = [a["username"] for a in anchors]
    with get_cursor() as cur:
        if anchor_ids:
            cur.execute(
                """UPDATE creators
                   SET last_scraped_as_anchor = NOW()
                   WHERE id = ANY(%s)""",
                (anchor_ids,),
            )
        cur.execute(
            """INSERT INTO discovery_batches
                   (batch_date, batch_type, anchor_seeds, exploration_ratio, raw_discovered)
               VALUES (%s, 'daily_l1', %s, 0, 0)""",
            (date.today(), usernames),
        )

    seed_cnt = sum(1 for a in anchors if a["strategy"] == "seed_following")
    passed_cnt = len(anchors) - seed_cnt
    logger.info(
        "Generated %d anchors (%d seeds + %d passed creators) out of %d candidates (cap=%d)",
        len(anchors), seed_cnt, passed_cnt, len(rows), DAILY_ANCHOR_COUNT,
    )
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
        if APIFY_BUDGET_HARD_LIMIT:
            logger.warning("Daily Apify budget exceeded ($%.2f >= $%.2f) — blocking", today_cost, DAILY_APIFY_BUDGET_USD)
            return {"runs_started": 0, "budget_ok": False, "stored": 0}
        logger.warning("Daily Apify budget exceeded ($%.2f >= $%.2f) — continuing anyway", today_cost, DAILY_APIFY_BUDGET_USD)

    with open(APIFY_CONFIG_PATH, encoding="utf-8") as f:
        apify_cfg = yaml.safe_load(f)

    cfg_key = "alt_following_actor" if APIFY_L1_ACTOR == "alt" else "following_actor"
    following_cfg = apify_cfg[cfg_key]
    actor_id = following_cfg["actor_id"]
    base_input = following_cfg["input"].copy()

    client = ApifyClient(APIFY_API_TOKEN)
    handles = [a["username"] for a in anchors if not a["username"].startswith("#")]

    if not handles:
        logger.info("No valid handles to scan")
        return {"runs_started": 0, "budget_ok": True}

    # 兼容不同 Actor 的 handles 字段名
    for key in ("twitterHandles", "usernames", "handles"):
        if key in base_input:
            base_input[key] = handles
            break
    cap = max_following if max_following is not None else MAX_FOLLOWING_PER_ANCHOR
    for key in ("maxItems", "maxResults", "max_items"):
        if key in base_input:
            base_input[key] = cap
            break

    run = client.actor(actor_id).call(run_input=base_input)
    run_id = run.get("id", "")
    usage_usd = float(run.get("usageTotalUsd") or 0.0)
    if usage_usd > 0:
        upsert_cost(date.today(), apify_cost_usd=usage_usd)
    logger.info("Apify run completed: %s (cost=$%.4f)", run_id, usage_usd)

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
