"""不调用 LLM，用占位符跑通 DNA 数据链路。

为所有 seeds + interested 创作者写入：
- 规则推断的商业信号、地区分层、基础数据特征
- 默认占位符内容分类（anime）

Usage:
    .venv/bin/python scripts/run_dna_pipeline_no_llm.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.creator_dna import analyze_creator_dna

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    # 开发模式下 DNA_LLM_ENABLED=false，analyze_creator_dna 会自动使用占位符
    from db.connection import fetch_all

    rows = fetch_all(
        """SELECT c.id, c.username
           FROM creators c
           WHERE c.is_seed = true OR c.bd_decision = 'interested'
           ORDER BY c.id"""
    )
    logger.info("Running DNA pipeline (no LLM) for %d creators", len(rows))

    success = failed = 0
    for row in rows:
        try:
            result = analyze_creator_dna(row["id"])
            if result:
                success += 1
            else:
                failed += 1
        except Exception:
            logger.exception("Failed for creator %d", row["id"])
            failed += 1

    logger.info("Done: success=%d, failed=%d", success, failed)


if __name__ == "__main__":
    main()
