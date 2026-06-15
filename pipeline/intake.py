"""公共数据入库 + 规则/AI 过滤 — 供 webhook 和 discovery 同步模式共用。"""

import asyncio
import logging

from apify_client import ApifyClient

from db.connection import fetch_all, fetch_one, get_cursor

logger = logging.getLogger(__name__)


def _store_graph_relations(relations: list[tuple[str, str]]) -> int:
    """Batch-write following relations into creator_graph.

    Returns number of rows inserted.
    """
    if not relations:
        return 0

    unique_relations = list(set(relations))
    all_handles = set()
    for src, tgt in unique_relations:
        all_handles.add(src)
        all_handles.add(tgt)

    rows = fetch_all(
        "SELECT id, username FROM creators WHERE username = ANY(%s)",
        (list(all_handles),),
    )
    handle_to_id = {row["username"].lower(): row["id"] for row in rows}

    values = []
    for src, tgt in unique_relations:
        src_id = handle_to_id.get(src)
        tgt_id = handle_to_id.get(tgt)
        if src_id and tgt_id:
            values.append((src_id, tgt_id, "follow"))

    if not values:
        return 0

    from psycopg2.extras import execute_values

    with get_cursor() as cur:
        execute_values(
            cur,
            """INSERT INTO creator_graph (creator_id, connected_creator_id, connection_type)
               VALUES %s
               ON CONFLICT DO NOTHING""",
            values,
            template="(%s, %s, %s)",
        )
        return cur.rowcount


def store_dataset_items(items: list[dict]) -> dict:
    """Upsert Apify dataset items into creators table + write following edges.

    Returns: {total, inserted, updated, usernames: set[str]}.
    """
    inserted = updated = 0
    usernames: set[str] = set()
    relations: list[tuple[str, str]] = []

    for item in items:
        username = (
            item.get("username") or item.get("screen_name")
            or item.get("userName") or ""
        )
        if not username:
            continue
        username = username.lstrip("@").lower()
        usernames.add(username)

        # Extract following relation from Apify source metadata
        source = item.get("inputSource") or item.get("followedBy") or ""
        if source:
            source = source.lstrip("@").lower()
            if source != username:
                relations.append((source, username))

        bio = item.get("description") or item.get("bio") or ""
        # FIXME: creators.website 设计语义是“个人主页或店铺链接”，Twitter/X 主页 URL
        # 不应写入该字段。当前仅保留 Apify 明确提供的 website，避免 url 污染变现判断逻辑。
        website = item.get("website") or ""
        followers = item.get("followers") or item.get("followersCount") or 0
        following = item.get("following") or item.get("friendsCount") or 0
        tweets_count = item.get("statusesCount") or item.get("tweetsCount") or 0

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
                   RETURNING (xmax = 0) AS is_insert""",
                (username, bio, website, followers, following, tweets_count, username),
            )
            row = cur.fetchone()
            if row and row["is_insert"]:
                inserted += 1
            else:
                updated += 1

            # 追加 snapshot（同一事务）
            cur.execute(
                "SELECT id, is_seed FROM creators WHERE platform_account_id = %s",
                (username,),
            )
            creator_info = cur.fetchone()
            if creator_info and followers > 0:
                table = (
                    "seed_follower_snapshots"
                    if creator_info.get("is_seed")
                    else "creator_snapshots"
                )
                cur.execute(
                    f"""
                    INSERT INTO {table} (creator_id, observed_at, followers, following, tweets_count, source)
                    VALUES (%s, DATE_TRUNC('day', NOW()), %s, %s, %s, 'intake')
                    ON CONFLICT (creator_id, observed_at) DO UPDATE SET
                        followers = EXCLUDED.followers,
                        following = EXCLUDED.following,
                        tweets_count = EXCLUDED.tweets_count,
                        source = EXCLUDED.source
                    """,
                    (creator_info["id"], followers, following, tweets_count),
                )

    graph_inserted = _store_graph_relations(relations)
    if graph_inserted:
        logger.info("Inserted %d creator_graph edges", graph_inserted)

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
            ctype = r.get("type")
            with get_cursor() as cur:
                if ctype:
                    cur.execute(
                        "UPDATE creators SET bd_status = %s, creator_type_auto = %s WHERE id = %s",
                        (status, ctype, r["bio_id"]),
                    )
                else:
                    cur.execute(
                        "UPDATE creators SET bd_status = %s WHERE id = %s",
                        (status, r["bio_id"]),
                    )
            if status == "ai_passed":
                stats["ai_passed"] += 1
            else:
                stats["ai_rejected"] += 1

    logger.info("Filter pipeline: %s", stats)
    return stats


def tag_discovery_source(
    usernames: set[str],
    strategy: str,
    anchor_seed: str | None = None,
    discovered_via: str | None = None,
) -> int:
    """回写 discovery_strategy / anchor_seed / discovered_via（仅更新尚未标记的行）。"""
    if not usernames:
        return 0
    with get_cursor() as cur:
        cur.execute(
            """UPDATE creators
               SET discovery_strategy = %s,
                   anchor_seed = %s,
                   discovered_via = %s
               WHERE username = ANY(%s)
                 AND discovery_strategy IS NULL""",
            (strategy, anchor_seed, discovered_via, list(usernames)),
        )
        count = cur.rowcount
    if count:
        logger.info("Tagged %d creators: strategy=%s, anchor=%s", count, strategy, anchor_seed)
    return count


def process_dataset(client: ApifyClient, dataset_id: str) -> dict:
    """Fetch dataset from Apify, store items, and run filter pipeline.

    Convenience wrapper used by both webhook and discovery sync mode.
    包含 dataset_id 去重，防止 webhook 与同步路径重复处理同一数据集。
    """
    # 去重检查
    dup = fetch_one(
        "SELECT 1 FROM processed_datasets WHERE dataset_id = %s",
        (dataset_id,),
    )
    if dup:
        logger.info("Dataset %s already processed, skipping", dataset_id)
        return {"store": {}, "filter": {}, "skipped": True}

    items = list(client.dataset(dataset_id).iterate_items())
    logger.info("Fetched %d items from dataset %s", len(items), dataset_id)

    store_stats = store_dataset_items(items)
    usernames = store_stats.pop("usernames", set())
    logger.info("Stored: %s", store_stats)

    filter_stats = run_filter_pipeline(usernames=usernames)

    # 记录已处理，防止重复消费
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO processed_datasets (dataset_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (dataset_id,),
        )

    return {"store": store_stats, "filter": filter_stats}
