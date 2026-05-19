"""功能验证脚本：确认 intake.py AI filter 回写时 creator_type_auto 被正确写入。"""

import os
import sys

# 强制使用测试数据库，避免误连生产
os.environ["DATABASE_URL"] = "postgresql://testuser:testpass@localhost:5433/testdb"

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from db.connection import get_cursor
from pipeline.intake import run_filter_pipeline


def setup():
    """确保测试表干净。"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM creators WHERE username LIKE 'test_intake_%'")


def teardown():
    """清理测试数据。"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM creators WHERE username LIKE 'test_intake_%'")


def insert_test_user(username: str, bio: str):
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO creators (username, platform, platform_account_id, bio, bd_status)
               VALUES (%s, 'twitter', %s, %s, 'pending')
               RETURNING id""",
            (username, username, bio),
        )
        row = cur.fetchone()
        return row["id"]


def fetch_user(username: str):
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, username, bd_status, creator_type_auto FROM creators WHERE username = %s",
            (username,),
        )
        return cur.fetchone()


def test_ai_filter_writes_type():
    """场景1：AI 返回 type=oc_creator，应同时写入 bd_status 和 creator_type_auto。"""
    username = "test_intake_01"
    user_id = insert_test_user(username, "illustrator | commissions open")

    with patch(
        "pipeline.bio_rule_filter.BioRuleFilter.filter",
        return_value={"passed": None},
    ):
        with patch(
            "pipeline.ai_filter.AIFilter.filter_batch",
            return_value=[
                {"bio_id": user_id, "result": "YES", "type": "oc_creator", "confidence": 0.95},
            ],
        ):
            stats = run_filter_pipeline(usernames={username})

    row = fetch_user(username)
    assert row["bd_status"] == "ai_passed", f"期望 ai_passed，实际 {row['bd_status']}"
    assert row["creator_type_auto"] == "oc_creator", f"期望 oc_creator，实际 {row['creator_type_auto']}"
    assert stats["ai_passed"] == 1
    print(f"[PASS] test_ai_filter_writes_type: {dict(row)}")


def test_ai_filter_skips_null_type():
    """场景2：AI 返回 type=None，应只写入 bd_status，不覆盖 creator_type_auto。"""
    username = "test_intake_02"
    user_id = insert_test_user(username, "random bio text")

    with patch(
        "pipeline.bio_rule_filter.BioRuleFilter.filter",
        return_value={"passed": None},
    ):
        with patch(
            "pipeline.ai_filter.AIFilter.filter_batch",
            return_value=[
                {"bio_id": user_id, "result": "NO", "type": None, "confidence": 0.1},
            ],
        ):
            stats = run_filter_pipeline(usernames={username})

    row = fetch_user(username)
    assert row["bd_status"] == "ai_rejected", f"期望 ai_rejected，实际 {row['bd_status']}"
    assert row["creator_type_auto"] is None, f"期望 None，实际 {row['creator_type_auto']}"
    assert stats["ai_rejected"] == 1
    print(f"[PASS] test_ai_filter_skips_null_type: {dict(row)}")


def test_ai_filter_rejected_but_has_type():
    """场景3：AI 判定为 NO 但仍返回 type，应写入 bd_status=ai_rejected 并保留 type。"""
    username = "test_intake_03"
    user_id = insert_test_user(username, "some bio")

    with patch(
        "pipeline.bio_rule_filter.BioRuleFilter.filter",
        return_value={"passed": None},
    ):
        with patch(
            "pipeline.ai_filter.AIFilter.filter_batch",
            return_value=[
                {"bio_id": user_id, "result": "NO", "type": "fan_artist", "confidence": 0.4},
            ],
        ):
            stats = run_filter_pipeline(usernames={username})

    row = fetch_user(username)
    assert row["bd_status"] == "ai_rejected"
    assert row["creator_type_auto"] == "fan_artist", f"期望 fan_artist，实际 {row['creator_type_auto']}"
    assert stats["ai_rejected"] == 1
    print(f"[PASS] test_ai_filter_rejected_but_has_type: {dict(row)}")


if __name__ == "__main__":
    setup()
    try:
        test_ai_filter_writes_type()
        test_ai_filter_skips_null_type()
        test_ai_filter_rejected_but_has_type()
        print("\n✅ 全部功能验证通过")
    finally:
        teardown()
