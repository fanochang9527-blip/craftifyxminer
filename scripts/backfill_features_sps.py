#!/usr/bin/env python3
"""批量补算 creator_features 与 creator_scores（有推文、尚无特征/评分的创作者）。

用法（项目根、已激活 venv）::

    python scripts/backfill_features_sps.py
    python scripts/backfill_features_sps.py --max-rounds 5

依赖 .env 中 DATABASE_URL；不调用外网 API。
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
logger = logging.getLogger("backfill")


def main() -> int:
    import config.settings  # noqa: F401 — 加载 .env

    from pipeline.feature_engine import compute_all_pending
    from pipeline.sps_scorer import score_all_pending

    p = argparse.ArgumentParser(description="Backfill features + SPS for creators with tweets")
    p.add_argument("--max-rounds", type=int, default=5, help="最多循环轮数，直到本轮无新增")
    args = p.parse_args()

    total_f = total_s = 0
    for i in range(args.max_rounds):
        n_f = compute_all_pending()
        n_s = score_all_pending()
        total_f += n_f
        total_s += n_s
        logger.info("Round %d: +%d features, +%d scores", i + 1, n_f, n_s)
        if n_f == 0 and n_s == 0:
            break

    logger.info("Done: total +%d features, +%d scores", total_f, total_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
