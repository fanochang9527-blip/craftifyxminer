"""功能测试：验证 bd_decisions 表的多用户决策记录功能。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import fetch_all, fetch_one, get_cursor


def find_test_users():
    """找两个活跃的用户用于测试。"""
    users = fetch_all("SELECT id, username, role FROM users WHERE is_active = true ORDER BY id LIMIT 2")
    if len(users) < 2:
        print("❌ 需要至少 2 个活跃用户，当前只有", len(users))
        sys.exit(1)
    return users[0], users[1]


def find_test_creator():
    """找一个非种子创作者用于测试。"""
    creator = fetch_one(
        "SELECT id, username, bd_decision, bd_status FROM creators WHERE is_seed = false AND followers > 500 LIMIT 1"
    )
    if not creator:
        print("❌ 未找到合适的测试创作者")
        sys.exit(1)
    return creator


def simulate_user_decision(creator_id: int, user_id: int, decision: str):
    """模拟用户在 BD 审核工作台点击决策按钮。"""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO bd_decisions (creator_id, user_id, decision, previous_decision, updated_at)
            VALUES (%s, %s, %s,
                (SELECT decision FROM bd_decisions WHERE creator_id = %s AND user_id = %s),
                NOW()
            )
            ON CONFLICT (creator_id, user_id)
            DO UPDATE SET decision = EXCLUDED.decision,
                          previous_decision = EXCLUDED.previous_decision,
                          updated_at = NOW()
            """,
            (creator_id, user_id, decision, creator_id, user_id),
        )
        cur.execute(
            "UPDATE creators SET bd_decision = %s, bd_status = %s, last_bd_update = NOW() WHERE id = %s",
            (decision, decision, creator_id),
        )


def simulate_save_note(creator_id: int, user_id: int, note: str):
    """模拟用户保存备注。"""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO bd_decisions (creator_id, user_id, decision, note, updated_at)
            VALUES (%s, %s,
                COALESCE((SELECT decision FROM bd_decisions WHERE creator_id = %s AND user_id = %s), 'interested'),
                %s, NOW()
            )
            ON CONFLICT (creator_id, user_id)
            DO UPDATE SET note = EXCLUDED.note, updated_at = NOW()
            """,
            (creator_id, user_id, creator_id, user_id, note),
        )


def get_decision_stats(creator_id: int):
    """获取某创作者的所有用户决策统计。"""
    return fetch_one(
        """
        SELECT
            COUNT(*) FILTER (WHERE decision = 'interested') AS interested_count,
            COUNT(*) FILTER (WHERE decision = 'rejected_unfit') AS rejected_unfit_count,
            COUNT(*) FILTER (WHERE decision = 'rejected_not_creator') AS rejected_not_creator_count,
            STRING_AGG(u.username || ': ' || bd.decision, ', ' ORDER BY u.username) AS decisions_by_user
        FROM bd_decisions bd
        JOIN users u ON u.id = bd.user_id
        WHERE bd.creator_id = %s
        """,
        (creator_id,),
    )


def test_multi_user_decisions():
    print("=" * 60)
    print("功能测试：bd_decisions 多用户决策记录")
    print("=" * 60)

    user_a, user_b = find_test_users()
    creator = find_test_creator()

    print(f"\n测试用户 A: {user_a['username']} (id={user_a['id']})")
    print(f"测试用户 B: {user_b['username']} (id={user_b['id']})")
    print(f"测试创作者: @{creator['username']} (id={creator['id']})")
    print(f"创作者初始状态: bd_decision={creator['bd_decision']}, bd_status={creator['bd_status']}")

    # Step 1: 用户 A 点击感兴趣
    print("\n--- Step 1: 用户 A 点击感兴趣 ---")
    simulate_user_decision(creator["id"], user_a["id"], "interested")

    row = fetch_one(
        "SELECT * FROM bd_decisions WHERE creator_id = %s AND user_id = %s",
        (creator["id"], user_a["id"]),
    )
    assert row is not None, "❌ 用户 A 的决策未写入 bd_decisions"
    assert row["decision"] == "interested", f"❌ 决策应为 interested，实际是 {row['decision']}"
    assert row["previous_decision"] is None, f"❌ 首次决策 previous_decision 应为 NULL，实际是 {row['previous_decision']}"
    print(f"✅ 用户 A 决策已记录: decision={row['decision']}, previous={row['previous_decision']}")

    # Step 2: 用户 B 点击不适合
    print("\n--- Step 2: 用户 B 点击不适合 ---")
    simulate_user_decision(creator["id"], user_b["id"], "rejected_unfit")

    row = fetch_one(
        "SELECT * FROM bd_decisions WHERE creator_id = %s AND user_id = %s",
        (creator["id"], user_b["id"]),
    )
    assert row is not None, "❌ 用户 B 的决策未写入 bd_decisions"
    assert row["decision"] == "rejected_unfit", f"❌ 决策应为 rejected_unfit，实际是 {row['decision']}"
    print(f"✅ 用户 B 决策已记录: decision={row['decision']}, previous={row['previous_decision']}")

    # Step 3: 验证两位用户的决策互不覆盖
    print("\n--- Step 3: 验证多用户决策互不覆盖 ---")
    decisions = fetch_all(
        "SELECT user_id, decision FROM bd_decisions WHERE creator_id = %s ORDER BY user_id",
        (creator["id"],),
    )
    assert len(decisions) == 2, f"❌ 应有 2 条决策记录，实际有 {len(decisions)}"
    print(f"✅ 该创作者共有 {len(decisions)} 条用户决策记录")
    for d in decisions:
        print(f"   user_id={d['user_id']}, decision={d['decision']}")

    # Step 4: 用户 A 变更决策（感兴趣 → 不适合）
    print("\n--- Step 4: 用户 A 变更决策（感兴趣 → 不适合）---")
    simulate_user_decision(creator["id"], user_a["id"], "rejected_unfit")

    row = fetch_one(
        "SELECT * FROM bd_decisions WHERE creator_id = %s AND user_id = %s",
        (creator["id"], user_a["id"]),
    )
    assert row["decision"] == "rejected_unfit", f"❌ 决策应更新为 rejected_unfit"
    assert row["previous_decision"] == "interested", f"❌ previous_decision 应为 interested，实际是 {row['previous_decision']}"
    print(f"✅ 用户 A 决策已更新: decision={row['decision']}, previous={row['previous_decision']}")

    # Step 5: 验证决策统计查询
    print("\n--- Step 5: 验证决策统计查询 ---")
    stats = get_decision_stats(creator["id"])
    assert stats["interested_count"] == 0, f"❌ interested_count 应为 0，实际是 {stats['interested_count']}"
    assert stats["rejected_unfit_count"] == 2, f"❌ rejected_unfit_count 应为 2，实际是 {stats['rejected_unfit_count']}"
    print(f"✅ 决策统计: interested={stats['interested_count']}, rejected_unfit={stats['rejected_unfit_count']}")
    print(f"   决策明细: {stats['decisions_by_user']}")

    # Step 6: 用户 A 保存备注
    print("\n--- Step 6: 用户 A 保存备注 ---")
    simulate_save_note(creator["id"], user_a["id"], "很有潜力的创作者，建议跟进")

    row = fetch_one(
        "SELECT note FROM bd_decisions WHERE creator_id = %s AND user_id = %s",
        (creator["id"], user_a["id"]),
    )
    assert row["note"] == "很有潜力的创作者，建议跟进", f"❌ note 保存失败"
    print(f"✅ 用户 A 备注已保存: '{row['note']}'")

    # Step 7: 验证 creators 表全局状态也被更新
    print("\n--- Step 7: 验证 creators 表全局状态 ---")
    updated = fetch_one("SELECT bd_decision, bd_status FROM creators WHERE id = %s", (creator["id"],))
    assert updated["bd_decision"] == "rejected_unfit", f"❌ creators.bd_decision 未更新"
    assert updated["bd_status"] == "rejected_unfit", f"❌ creators.bd_status 未更新"
    print(f"✅ creators 全局状态: bd_decision={updated['bd_decision']}, bd_status={updated['bd_status']}")

    # Step 8: 验证 outreach 查询可用
    print("\n--- Step 8: 验证 outreach 查询（存在 interested 决策）---")
    # 先把用户 B 改为 interested，让 outreach 查询能查到
    simulate_user_decision(creator["id"], user_b["id"], "interested")
    outreach_rows = fetch_all(
        """
        SELECT c.id, c.username,
               (SELECT STRING_AGG(u.username, ', ')
                FROM bd_decisions bd
                JOIN users u ON u.id = bd.user_id
                WHERE bd.creator_id = c.id AND bd.decision = 'interested') AS interested_users
        FROM creators c
        WHERE EXISTS (
            SELECT 1 FROM bd_decisions bd
            WHERE bd.creator_id = c.id AND bd.decision = 'interested'
        )
          AND c.id = %s
        """,
        (creator["id"],),
    )
    assert len(outreach_rows) == 1, f"❌ outreach 查询应返回 1 行，实际返回 {len(outreach_rows)}"
    assert user_b["username"] in outreach_rows[0]["interested_users"], f"❌ interested_users 应包含 {user_b['username']}"
    print(f"✅ Outreach 查询正常: interested_users={outreach_rows[0]['interested_users']}")

    print("\n" + "=" * 60)
    print("🎉 所有功能测试通过！")
    print("=" * 60)

    # 清理测试数据
    print("\n--- 清理测试数据 ---")
    with get_cursor() as cur:
        cur.execute("DELETE FROM bd_decisions WHERE creator_id = %s", (creator["id"],))
    print(f"✅ 已清理 creator_id={creator['id']} 的测试决策数据")


if __name__ == "__main__":
    test_multi_user_decisions()
