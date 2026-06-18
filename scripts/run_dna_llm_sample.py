"""小批量调用 LLM 验证 DNA 数据链路。

临时开启 LLM，跑前 N 个 eligible 创作者，验证 Apify + LLM pipeline 正常。

Usage:
    DNA_LLM_ENABLED=true .venv/bin/python scripts/run_dna_llm_sample.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 强制开启 LLM 和 Apify
os.environ["DNA_LLM_ENABLED"] = "true"
os.environ["DNA_APIFY_ENABLED"] = "true"

from db.connection import fetch_all
from pipeline.creator_dna import analyze_creator_dna

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SAMPLE_SIZE = 3


def main() -> None:
    rows = fetch_all(
        """SELECT c.id, c.username
           FROM creators c
           WHERE c.is_seed = true OR c.bd_decision = 'interested'
           ORDER BY c.id
           LIMIT %s""",
        (SAMPLE_SIZE,),
    )
    logger.info("Running LLM DNA sample for %d creators", len(rows))

    success = failed = 0
    for row in rows:
        try:
            result = analyze_creator_dna(row["id"])
            if result:
                logger.info("  -> creator %d: content=%s", row["id"], result.get("content_classifications"))
                success += 1
            else:
                failed += 1
        except Exception:
            logger.exception("Failed for creator %d", row["id"])
            failed += 1

    logger.info("Done: success=%d, failed=%d", success, failed)


if __name__ == "__main__":
    main()
