"""冒烟测试：触发小规模 L1 scan，验证 creator_graph 自动写入 + 中心度生效。"""

import sys

sys.path.insert(0, "/opt/craftifyxminer")

from db.connection import fetch_all, fetch_one  # noqa: E402
from pipeline.discovery import trigger_l1_scan  # noqa: E402
from pipeline.sps_scorer import score_all_pending  # noqa: E402


def main() -> None:
    print("=== Step 1: 记录测试前 creator_graph 数量 ===")
    before = fetch_one("SELECT COUNT(*) AS cnt FROM creator_graph")
    before_cnt = before["cnt"] if before else 0
    print(f"Before: {before_cnt} rows")

    print("\n=== Step 2: 触发小规模 L1 scan（1 个种子，max_following=10）===")
    anchors = [
        {"username": "fishchunk88", "strategy": "seed_following", "seed_id": 52}
    ]
    result = trigger_l1_scan(anchors=anchors, max_following=10)
    print(f"Result: {result}")

    print("\n=== Step 3: 检查 creator_graph 增量 ===")
    after = fetch_one("SELECT COUNT(*) AS cnt FROM creator_graph")
    after_cnt = after["cnt"] if after else 0
    delta = after_cnt - before_cnt
    print(f"After: {after_cnt} rows (+{delta})")

    if delta > 0:
        print("✅ creator_graph 有新数据写入")
        # 查看最新插入的几条
        edges = fetch_all(
            """SELECT cg.*, c1.username AS source_name, c2.username AS target_name
               FROM creator_graph cg
               JOIN creators c1 ON c1.id = cg.creator_id
               JOIN creators c2 ON c2.id = cg.connected_creator_id
               ORDER BY cg.created_at DESC
               LIMIT 5"""
        )
        print("\nLatest edges:")
        for e in edges:
            print(f"  {e['source_name']} -> {e['target_name']} ({e['connection_type']})")
    else:
        print("⚠️ creator_graph 无变化 — 可能 intake.py 未生效或 Apify 未返回数据")

    print("\n=== Step 4: 重新评分并检查中心度分布 ===")
    score_all_pending()
    stats = fetch_all(
        """SELECT centrality_tier, COUNT(*) AS cnt
           FROM creator_scores
           GROUP BY centrality_tier
           ORDER BY cnt DESC"""
    )
    print("Current centrality distribution:")
    for s in stats:
        print(f"  {s['centrality_tier'] or 'NULL'}: {s['cnt']}")

    print("\n=== Step 5: 检查 Hub 示例 ===")
    hubs = fetch_all(
        """SELECT c.username, cs.sps_score, cs.seed_connections, cs.centrality_tier
           FROM creator_scores cs
           JOIN creators c ON c.id = cs.creator_id
           WHERE cs.centrality_tier = 'Hub'
           ORDER BY cs.seed_connections DESC
           LIMIT 5"""
    )
    if hubs:
        print("Top Hubs:")
        for h in hubs:
            print(f"  @{h['username']}: seed_connections={h['seed_connections']}, sps={h['sps_score']}")
    else:
        print("No Hub found.")

    print("\n=== Smoke test complete ===")


if __name__ == "__main__":
    main()
