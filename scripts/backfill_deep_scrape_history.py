#!/usr/bin/env python3
"""补算历史积压的深度抓取（不含今天新产生的 passed 候选人）。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import fetch_all
from pipeline.deep_scrape import trigger_seed_deep_scrape


def get_backlog_usernames() -> list[str]:
    rows = fetch_all(
        """
        SELECT username
        FROM creators
        WHERE bd_status IN ('rule_passed', 'ai_passed')
          AND discovered_date < CURRENT_DATE
          AND id NOT IN (
              SELECT DISTINCT creator_id FROM tweets
              WHERE creator_id IS NOT NULL
                AND collected_at > NOW() - INTERVAL '30 days'
          )
        ORDER BY first_seen_at ASC
        """
    )
    return [r["username"] for r in rows]


def main():
    usernames = get_backlog_usernames()
    if not usernames:
        print("没有历史积压的 passed 候选人需要深度抓取。")
        return

    print(f"准备深度抓取 {len(usernames)} 个历史积压候选人:")
    for u in usernames:
        print(f"  - @{u}")

    result = trigger_seed_deep_scrape(usernames)
    print(f"\n完成: {result}")


if __name__ == "__main__":
    main()
