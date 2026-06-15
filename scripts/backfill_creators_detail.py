"""全量补填 creators_detail 表。

扫描所有 is_seed=true 或 bd_decision='interested' 的创作者，
调用 pipeline.creator_detail_sync.sync_creator_detail 写入/更新详情档案。

用法：
    python scripts/backfill_creators_detail.py [--limit N]
"""

import argparse
import logging

from pipeline.creator_detail_sync import sync_all_eligible

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Backfill creators_detail for eligible creators")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少条创作者（默认全部）")
    parser.add_argument("--source", type=str, default="backfill", help="同步来源标记")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    result = sync_all_eligible(limit=args.limit, sync_source=args.source)
    print(f"Backfill complete: {result}")


if __name__ == "__main__":
    main()
