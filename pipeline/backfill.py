"""基于 anchor_seed 字段回刷 creator_graph 历史关系并重新计算中心度。

解析策略：anchor_seed 格式为 "@a, @b, @c, @d, @e (+N)"，按 ", " 分割并去 @ 符号，
与 creators.username 精确匹配。
"""

import logging

from db.connection import fetch_all, get_cursor
from pipeline.sps_scorer import score_creator

logger = logging.getLogger(__name__)


def parse_seed_usernames(anchor_seed: str | None) -> list[str]:
    if not anchor_seed:
        return []
    # 去掉 "(+N)" 后缀
    text = anchor_seed.split("(")[0]
    # 按 ", " 分割，去掉 @ 符号和首尾空格
    parts = [p.strip().lstrip("@") for p in text.split(",")]
    return [p for p in parts if p]


def run_backfill() -> dict:
    """Backfill creator_graph edges from anchor_seed and recalculate centrality tiers.

    Returns:
        {
            "creators_with_anchor": int,
            "unique_seeds_parsed": int,
            "relations_prepared": int,
            "relations_inserted": int,
            "scores_total": int,
            "scores_updated": int,
            "centrality_distribution": dict,
        }
    """
    logger.info("Fetching creators with anchor_seed...")
    rows = fetch_all(
        """SELECT id, username, anchor_seed
           FROM creators
           WHERE anchor_seed IS NOT NULL
             AND is_seed = false"""
    )
    creators_with_anchor = len(rows)
    logger.info("Found %d non-seed creators with anchor_seed", creators_with_anchor)

    # 收集所有解析出的种子 username
    all_seed_usernames: set[str] = set()
    for row in rows:
        all_seed_usernames.update(parse_seed_usernames(row["anchor_seed"]))
    unique_seeds_parsed = len(all_seed_usernames)
    logger.info("Parsed %d unique seed usernames from anchor_seed", unique_seeds_parsed)

    if not all_seed_usernames:
        logger.info("No seed usernames parsed.")
        return {
            "creators_with_anchor": creators_with_anchor,
            "unique_seeds_parsed": 0,
            "relations_prepared": 0,
            "relations_inserted": 0,
            "scores_total": 0,
            "scores_updated": 0,
            "centrality_distribution": {},
        }

    seeds = fetch_all(
        """SELECT id, username FROM creators
            WHERE is_seed = true
              AND username = ANY(%s)""",
        (list(all_seed_usernames),),
    )
    seed_id_map = {row["username"]: row["id"] for row in seeds}
    logger.info("Matched %d seed usernames to DB IDs", len(seed_id_map))
    if len(seed_id_map) < 10:
        logger.info("  Matched seeds: %s", list(seed_id_map.keys()))
    unmatched = all_seed_usernames - set(seed_id_map.keys())
    if unmatched:
        logger.info("  Unmatched seeds (%d): %s", len(unmatched), list(unmatched)[:20])

    relations: list[tuple[int, int]] = []
    for row in rows:
        creator_id = row["id"]
        seed_names = parse_seed_usernames(row["anchor_seed"])
        for name in seed_names:
            seed_id = seed_id_map.get(name)
            if seed_id:
                relations.append((seed_id, creator_id))

    if not relations:
        logger.info("No valid relations to insert.")
        return {
            "creators_with_anchor": creators_with_anchor,
            "unique_seeds_parsed": unique_seeds_parsed,
            "relations_prepared": 0,
            "relations_inserted": 0,
            "scores_total": 0,
            "scores_updated": 0,
            "centrality_distribution": {},
        }

    unique_relations = list(set(relations))
    relations_prepared = len(unique_relations)
    logger.info("Prepared %d unique relations", relations_prepared)

    from psycopg2.extras import execute_values

    with get_cursor() as cur:
        execute_values(
            cur,
            """INSERT INTO creator_graph (creator_id, connected_creator_id, connection_type)
               VALUES %s
               ON CONFLICT DO NOTHING""",
            [(s, t, "follow") for s, t in unique_relations],
            template="(%s, %s, %s)",
        )
        relations_inserted = cur.rowcount
    logger.info("Inserted %d rows into creator_graph", relations_inserted)

    # 重新计算所有已有 creator_scores 的 seed_connections / centrality_tier
    logger.info("Recalculating creator_scores for all scored creators...")
    score_rows = fetch_all(
        """SELECT creator_id FROM creator_scores
           WHERE sps_score IS NOT NULL"""
    )
    scores_total = len(score_rows)
    scores_updated = 0
    for row in score_rows:
        result = score_creator(row["creator_id"])
        if result:
            scores_updated += 1
    logger.info("Updated %d creator_scores", scores_updated)

    # 快速统计
    stats = fetch_all(
        """SELECT centrality_tier, COUNT(*) AS cnt
           FROM creator_scores
           GROUP BY centrality_tier"""
    )
    centrality_distribution = {s["centrality_tier"] or "NULL": s["cnt"] for s in stats}
    logger.info("Centrality distribution after backfill: %s", centrality_distribution)

    return {
        "creators_with_anchor": creators_with_anchor,
        "unique_seeds_parsed": unique_seeds_parsed,
        "relations_prepared": relations_prepared,
        "relations_inserted": relations_inserted,
        "scores_total": scores_total,
        "scores_updated": scores_updated,
        "centrality_distribution": centrality_distribution,
    }
