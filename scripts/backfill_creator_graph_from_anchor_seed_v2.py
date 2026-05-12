"""基于 anchor_seed 字段近似回刷 creator_graph 历史关系（v2）。

解析策略：anchor_seed 格式为 "@a, @b, @c, @d, @e (+N)"，按 ", " 分割并去 @ 符号，
与 creators.username 精确匹配。
"""

import sys

sys.path.insert(0, "/opt/craftifyxminer")

from db.connection import fetch_all, get_cursor  # noqa: E402
from pipeline.sps_scorer import score_creator  # noqa: E402


def parse_seed_usernames(anchor_seed: str | None) -> list[str]:
    if not anchor_seed:
        return []
    # 去掉 "(+N)" 后缀
    text = anchor_seed.split("(")[0]
    # 按 ", " 分割，去掉 @ 符号和首尾空格
    parts = [p.strip().lstrip("@") for p in text.split(",")]
    return [p for p in parts if p]


def main() -> None:
    print("Fetching creators with anchor_seed...")
    rows = fetch_all(
        """SELECT id, username, anchor_seed
           FROM creators
           WHERE anchor_seed IS NOT NULL
             AND is_seed = false"""
    )
    print(f"Found {len(rows)} non-seed creators with anchor_seed")

    # 收集所有解析出的种子 username
    all_seed_usernames = set()
    for row in rows:
        all_seed_usernames.update(parse_seed_usernames(row["anchor_seed"]))
    print(f"Parsed {len(all_seed_usernames)} unique seed usernames from anchor_seed")

    # 查询哪些对应 is_seed=true
    if not all_seed_usernames:
        print("No seed usernames parsed.")
        return

    seeds = fetch_all(
        """SELECT id, username FROM creators
            WHERE is_seed = true
              AND username = ANY(%s)""",
        (list(all_seed_usernames),),
    )
    seed_id_map = {row["username"]: row["id"] for row in seeds}
    print(f"Matched {len(seed_id_map)} seed usernames to DB IDs")
    if len(seed_id_map) < 10:
        print(f"  Matched seeds: {list(seed_id_map.keys())}")
    unmatched = all_seed_usernames - set(seed_id_map.keys())
    if unmatched:
        print(f"  Unmatched seeds ({len(unmatched)}): {list(unmatched)[:20]}")

    relations = []
    for row in rows:
        creator_id = row["id"]
        seed_names = parse_seed_usernames(row["anchor_seed"])
        for name in seed_names:
            seed_id = seed_id_map.get(name)
            if seed_id:
                relations.append((seed_id, creator_id))

    if not relations:
        print("No valid relations to insert.")
        return

    unique_relations = list(set(relations))
    print(f"Prepared {len(unique_relations)} unique relations")

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
        inserted = cur.rowcount
    print(f"Inserted {inserted} rows into creator_graph")

    # 重新计算所有已有 creator_scores 的 seed_connections / centrality_tier
    print("\nRecalculating creator_scores for all scored creators...")
    score_rows = fetch_all(
        """SELECT creator_id FROM creator_scores
           WHERE sps_score IS NOT NULL"""
    )
    updated = 0
    for row in score_rows:
        result = score_creator(row["creator_id"])
        if result:
            updated += 1
    print(f"Updated {updated} creator_scores")

    # 快速统计
    stats = fetch_all(
        """SELECT centrality_tier, COUNT(*) AS cnt
           FROM creator_scores
           GROUP BY centrality_tier"""
    )
    print("\nCentrality distribution after backfill:")
    for s in stats:
        print(f"  {s['centrality_tier'] or 'NULL'}: {s['cnt']}")


if __name__ == "__main__":
    main()
