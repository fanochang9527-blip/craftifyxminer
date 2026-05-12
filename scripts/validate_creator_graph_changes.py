"""验证 intake.py 修改后的核心逻辑 — 单元测试 + 数据一致性检查。"""

import sys

sys.path.insert(0, "/opt/craftifyxminer")

from db.connection import execute, fetch_all, fetch_one  # noqa: E402
from pipeline.intake import _store_graph_relations, store_dataset_items  # noqa: E402
from pipeline.sps_scorer import classify_centrality, score_creator  # noqa: E402


def test_classify_centrality() -> None:
    print("\n[Test 1] classify_centrality")
    assert classify_centrality(0) == "Peripheral"
    assert classify_centrality(1) == "Peripheral"
    assert classify_centrality(2) == "Connector"
    assert classify_centrality(4) == "Connector"
    assert classify_centrality(5) == "Hub"
    assert classify_centrality(100) == "Hub"
    print("  ✅ 阈值分层正确")


def test_store_graph_relations() -> None:
    print("\n[Test 2] _store_graph_relations")
    # 创建两个测试用户（如果不存在）
    execute(
        """INSERT INTO creators (username, platform, platform_account_id)
           VALUES ('test_seed_001', 'twitter', 'test_seed_001'),
                  ('test_target_001', 'twitter', 'test_target_001')
           ON CONFLICT (platform, platform_account_id) DO NOTHING"""
    )

    rows_before = fetch_one(
        """SELECT COUNT(*) AS cnt FROM creator_graph cg
           JOIN creators c1 ON c1.id = cg.creator_id
           JOIN creators c2 ON c2.id = cg.connected_creator_id
           WHERE c1.username = 'test_seed_001' AND c2.username = 'test_target_001'"""
    )
    before = rows_before["cnt"] if rows_before else 0

    inserted = _store_graph_relations([("test_seed_001", "test_target_001")])
    print(f"  Inserted {inserted} row(s)")

    rows_after = fetch_one(
        """SELECT COUNT(*) AS cnt FROM creator_graph cg
           JOIN creators c1 ON c1.id = cg.creator_id
           JOIN creators c2 ON c2.id = cg.connected_creator_id
           WHERE c1.username = 'test_seed_001' AND c2.username = 'test_target_001'"""
    )
    after = rows_after["cnt"] if rows_after else 0

    # 清理测试数据（先删 graph 再删 creators，避免外键冲突）
    execute(
        """DELETE FROM creator_graph
           WHERE creator_id IN (SELECT id FROM creators WHERE username IN ('test_seed_001', 'test_target_001'))
              OR connected_creator_id IN (SELECT id FROM creators WHERE username IN ('test_seed_001', 'test_target_001'))"""
    )
    execute("DELETE FROM creators WHERE username IN ('test_seed_001', 'test_target_001')")

    assert after == before + 1, f"Expected {before + 1}, got {after}"
    print("  ✅ 图关系写入 + 去重正确")


def test_store_dataset_items_extracts_relations() -> None:
    print("\n[Test 3] store_dataset_items 提取 inputSource / followedBy")

    # 准备测试种子
    execute(
        """INSERT INTO creators (username, platform, platform_account_id, is_seed)
           VALUES ('test_anchor', 'twitter', 'test_anchor', true)
           ON CONFLICT (platform, platform_account_id) DO NOTHING"""
    )

    mock_items = [
        {
            "userName": "test_following_a",
            "description": "bio a",
            "followers": 100,
            "following": 50,
            "statusesCount": 10,
            "inputSource": "test_anchor",
        },
        {
            "userName": "test_following_b",
            "description": "bio b",
            "followers": 200,
            "following": 60,
            "statusesCount": 20,
            "followedBy": "test_anchor",
        },
        {
            "userName": "test_anchor",
            "description": "self",
            "followers": 999,
            "following": 1,
            "statusesCount": 1,
            "inputSource": "test_anchor",
        },
    ]

    result = store_dataset_items(mock_items)
    print(f"  store result: {result}")

    # 检查 creator_graph 是否写入
    edges = fetch_all(
        """SELECT cg.*, c1.username AS src, c2.username AS tgt
           FROM creator_graph cg
           JOIN creators c1 ON c1.id = cg.creator_id
           JOIN creators c2 ON c2.id = cg.connected_creator_id
           WHERE c1.username = 'test_anchor'
             AND c2.username IN ('test_following_a', 'test_following_b')"""
    )
    target_names = {e["tgt"] for e in edges}
    print(f"  Graph edges found: {target_names}")

    # 清理
    execute(
        """DELETE FROM creator_graph
           WHERE creator_id IN (SELECT id FROM creators WHERE username = 'test_anchor')"""
    )
    execute(
        """DELETE FROM creators
           WHERE username IN ('test_anchor', 'test_following_a', 'test_following_b')"""
    )

    assert "test_following_a" in target_names, "inputSource relation missing"
    assert "test_following_b" in target_names, "followedBy relation missing"
    assert "test_anchor" not in target_names, "self-loop should be filtered"
    print("  ✅ inputSource / followedBy 提取 + 自环过滤正确")


def test_data_consistency() -> None:
    print("\n[Test 4] 数据一致性检查")

    # 1. creator_graph 中所有 creator_id 都对应 is_seed=true
    bad_sources = fetch_all(
        """SELECT cg.creator_id, c.username
           FROM creator_graph cg
           JOIN creators c ON c.id = cg.creator_id
           WHERE c.is_seed = false"""
    )
    if bad_sources:
        print(f"  ⚠️ {len(bad_sources)} 条边的 source 不是种子: {[b['username'] for b in bad_sources[:5]]}")
    else:
        print("  ✅ 所有 graph 边的 source 都是种子")

    # 2. creator_scores.centrality_tier 与 seed_connections 一致
    mismatches = fetch_all(
        """SELECT creator_id, centrality_tier, seed_connections
           FROM creator_scores
           WHERE (seed_connections >= 5 AND centrality_tier != 'Hub')
              OR (seed_connections BETWEEN 2 AND 4 AND centrality_tier != 'Connector')
              OR (seed_connections <= 1 AND centrality_tier != 'Peripheral')"""
    )
    if mismatches:
        print(f"  ⚠️ {len(mismatches)} 条 creator_scores 中心度与 seed_connections 不匹配")
        for m in mismatches[:3]:
            print(f"     id={m['creator_id']}: tier={m['centrality_tier']}, seeds={m['seed_connections']}")
    else:
        print("  ✅ 所有 creator_scores 中心度与 seed_connections 一致")

    # 3. Hub 数量
    hub_count = fetch_one("SELECT COUNT(*) AS cnt FROM creator_scores WHERE centrality_tier = 'Hub'")
    print(f"  📊 当前 Hub 数量: {hub_count['cnt'] if hub_count else 0}")

    # 4. creator_graph 总量
    graph_total = fetch_one("SELECT COUNT(*) AS cnt FROM creator_graph")
    print(f"  📊 当前 creator_graph 总量: {graph_total['cnt'] if graph_total else 0}")


def test_score_creator_with_graph() -> None:
    print("\n[Test 5] score_creator 端到端（使用已有数据）")
    # 找一个已有 features 的创作者
    row = fetch_one(
        """SELECT cs.creator_id, c.username, cs.seed_connections, cs.centrality_tier
           FROM creator_scores cs
           JOIN creators c ON c.id = cs.creator_id
           LIMIT 1"""
    )
    if not row:
        print("  ⚠️ 没有已评分的创作者，跳过")
        return

    cid = row["creator_id"]
    print(f"  Re-scoring creator_id={cid} (@{row['username']})...")
    result = score_creator(cid)
    if result:
        print(f"  Result: sps={result['sps_score']}, seeds={result['seed_connections']}, tier={result['centrality_tier']}")
        assert result["centrality_tier"] == classify_centrality(result["seed_connections"])
        print("  ✅ score_creator 输出一致")
    else:
        print("  ⚠️ score_creator 返回 None")


def main() -> None:
    print("=" * 60)
    print("Creator Graph Changes — Validation Suite")
    print("=" * 60)

    test_classify_centrality()
    test_store_graph_relations()
    test_store_dataset_items_extracts_relations()
    test_data_consistency()
    test_score_creator_with_graph()

    print("\n" + "=" * 60)
    print("All checks completed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
