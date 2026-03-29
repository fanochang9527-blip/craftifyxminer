#!/usr/bin/env python3
"""小批次跑通：L1（少量 following）→ 深度抓取 → 特征 → SPS。

用法（在项目根、已激活 venv）::

    python scripts/quick_smoke_pipeline.py
    python scripts/quick_smoke_pipeline.py --anchors 1 --max-following 30 --deep-limit 2

不必用 heredoc；本脚本通过 import config.settings 加载根目录 .env。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("quick_smoke")


def main() -> int:
    import config.settings  # noqa: F401 — 加载 .env
    from db.connection import fetch_all
    from pipeline.runner import run_full_pipeline

    p = argparse.ArgumentParser(description="Quick smoke: L1 + deep scrape + features + SPS")
    p.add_argument("--anchors", type=int, default=1, help="种子锚点数量（默认 1）")
    p.add_argument("--max-following", type=int, default=40, help="每个 run 的 maxItems 上限（默认 40）")
    p.add_argument("--deep-limit", type=int, default=3, help="深度抓取人数（默认 3）")
    p.add_argument("--skip-l1", action="store_true", help="跳过 L1，只做 deep + 评分")
    args = p.parse_args()

    anchors = None
    if not args.skip_l1:
        seeds = fetch_all(
            """SELECT id, username FROM creators
               WHERE is_seed = true AND seed_tier IN ('S', 'A', 'B')
               ORDER BY CASE seed_tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 ELSE 3 END, id
               LIMIT %s""",
            (args.anchors,),
        )
        if not seeds:
            logger.error("No seed creators found")
            return 1
        anchors = [
            {"username": s["username"], "strategy": "smoke", "seed_id": s["id"]}
            for s in seeds
        ]

    result = run_full_pipeline(anchors=anchors, deep_limit=args.deep_limit)
    return 0 if result.get("status") == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
