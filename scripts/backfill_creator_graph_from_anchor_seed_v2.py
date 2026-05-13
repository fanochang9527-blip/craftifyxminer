"""基于 anchor_seed 字段近似回刷 creator_graph 历史关系（v2）。

解析策略：anchor_seed 格式为 "@a, @b, @c, @d, @e (+N)"，按 ", " 分割并去 @ 符号，
与 creators.username 精确匹配。

注意：核心逻辑已迁移至 pipeline.backfill，此脚本仅作为 CLI 入口保留。
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from pipeline.backfill import run_backfill  # noqa: E402


def main() -> None:
    result = run_backfill()
    print(f"\nBackfill summary:")
    print(f"  Creators with anchor_seed: {result['creators_with_anchor']}")
    print(f"  Unique seeds parsed:       {result['unique_seeds_parsed']}")
    print(f"  Relations prepared:        {result['relations_prepared']}")
    print(f"  Relations inserted:        {result['relations_inserted']}")
    print(f"  Scores total:              {result['scores_total']}")
    print(f"  Scores updated:            {result['scores_updated']}")
    print(f"  Centrality distribution:   {result['centrality_distribution']}")


if __name__ == "__main__":
    main()
