#!/usr/bin/env python3
"""多模态内容风格分析补算脚本。

对已完成深度抓取但尚未经过多模态 AI 模型判断的创作者进行补算。
复用 pipeline/content_style_filter.py 中的 ContentStyleFilter 类与结果写入逻辑，
确保补算行为与每日新数据流程完全一致。

筛选条件（与 pipeline 一致）：
  - creators 表中有记录
  - tweets 表中有该创作者的推文（代表已完成深度抓取）
  - creator_content_analysis 表中无任何记录（代表未进行过多模态判断）

使用方式（项目根目录、已激活 venv）::

    python scripts/backfill_content_style.py
    python scripts/backfill_content_style.py --batch-size 10
    python scripts/backfill_content_style.py --limit 500
    python scripts/backfill_content_style.py --dry-run
    python scripts/backfill_content_style.py --max-rounds 5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.connection import fetch_all
from pipeline.content_style_filter import (
    CONTENT_STYLE_ENABLED,
    ContentStyleFilter,
    _write_results,
)

logger = logging.getLogger("backfill_content_style")

_shutdown_requested = False


def _signal_handler(signum, _frame):
    global _shutdown_requested
    logger.info("Received signal %d, will exit after current batch...", signum)
    _shutdown_requested = True


def _get_backfill_candidates(limit: int) -> list[dict]:
    """获取已完成深度抓取但尚未进行内容风格分析的创作者。

    条件：
      - tweets 表中有该创作者的媒体推文（代表已深度抓取）
      - creator_content_analysis 表中无记录，或之前分析失败（status='failed'）
      - bd_status 为 rule_passed 或 ai_passed（与 pipeline 流程一致）
    """
    return fetch_all(
        """SELECT c.id, c.username
           FROM creators c
           JOIN tweets t ON t.creator_id = c.id
           LEFT JOIN creator_content_analysis cca ON cca.creator_id = c.id
           WHERE c.bd_status IN ('rule_passed', 'ai_passed')
             AND (cca.id IS NULL OR cca.status = 'failed')
           GROUP BY c.id, c.username
           LIMIT %s""",
        (limit,),
    )


def _get_backfill_count() -> int:
    """获取待补算创作者总数。"""
    row = fetch_all(
        """SELECT COUNT(DISTINCT c.id) AS cnt
           FROM creators c
           JOIN tweets t ON t.creator_id = c.id
           LEFT JOIN creator_content_analysis cca ON cca.creator_id = c.id
           WHERE c.bd_status IN ('rule_passed', 'ai_passed')
             AND (cca.id IS NULL OR cca.status = 'failed')"""
    )
    return row[0]["cnt"] if row else 0


def run_backfill(
    limit: int = 500,
    batch_size: int | None = None,
    dry_run: bool = False,
) -> dict:
    """执行一轮内容风格分析补算。

    Args:
        limit: 本轮最多处理的创作者数。
        batch_size: 每批并发分析的创作者数；None 则使用 ContentStyleFilter 默认配置。
        dry_run: 仅查询并打印候选人，不调用 LLM。

    Returns:
        {"candidates": int, "batches": int, "stats": dict | None,
         "dry_run": bool, "shutdown": bool}
    """
    if not CONTENT_STYLE_ENABLED:
        logger.info("Content style filter is disabled in settings")
        return {"candidates": 0, "batches": 0, "stats": None, "dry_run": dry_run, "shutdown": False}

    candidates = _get_backfill_candidates(limit)
    if not candidates:
        logger.info("No creators pending content style backfill")
        return {"candidates": 0, "batches": 0, "stats": None, "dry_run": dry_run, "shutdown": False}

    logger.info(
        "Content style backfill: %d candidates found (limit=%d)",
        len(candidates),
        limit,
    )

    if dry_run:
        for c in candidates:
            logger.info("  [dry-run] would process creator %d @%s", c["id"], c["username"])
        return {"candidates": len(candidates), "batches": 0, "stats": None, "dry_run": True, "shutdown": False}

    filter_obj = ContentStyleFilter()
    bs = batch_size if batch_size is not None else filter_obj.batch_size

    all_results: list[dict] = []
    batches_run = 0
    total = len(candidates)

    for i in range(0, total, bs):
        if _shutdown_requested:
            logger.info("Shutdown requested, stopping after current batch")
            break

        batch = candidates[i : i + bs]
        batch_num = batches_run + 1
        logger.info(
            "Processing batch %d/%d (%d creators: %s ...)",
            batch_num,
            (total + bs - 1) // bs,
            len(batch),
            ", ".join([f"@{c['username']}" for c in batch[:3]]),
        )

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(filter_obj.filter_batch(batch))
            all_results.extend(results)
        except Exception:
            logger.exception("Batch %d failed", batch_num)
        finally:
            loop.close()

        batches_run += 1
        logger.info(
            "Batch %d complete — progress %d/%d creators",
            batch_num,
            min(i + bs, total),
            total,
        )

    # 写入数据库
    stats = _write_results(all_results)
    logger.info("Backfill round complete: %s", stats)

    return {
        "candidates": len(candidates),
        "batches": batches_run,
        "stats": stats,
        "dry_run": False,
        "shutdown": _shutdown_requested,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="Backfill multimodal content style analysis for deep-scraped creators."
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Concurrent creators per LLM batch (default: ContentStyleFilter config).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum creators to process per round (default: 500).",
    )
    p.add_argument(
        "--max-rounds",
        type=int,
        default=5,
        help="Maximum rounds to run; stops early if no candidates remain (default: 5).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print candidates without calling LLM or writing to DB.",
    )
    p.add_argument(
        "--count-only",
        action="store_true",
        help="Print total pending count and exit.",
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.count_only:
        pending = _get_backfill_count()
        print(f"Pending creators for content style backfill: {pending}")
        return 0

    if args.dry_run:
        result = run_backfill(limit=args.limit, batch_size=args.batch_size, dry_run=True)
        logger.info("Dry-run result: %s", result)
        return 0

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    total_candidates = 0
    total_analyzed = 0
    total_passed = 0
    total_rejected = 0
    total_skipped = 0
    total_failed = 0

    for round_num in range(1, args.max_rounds + 1):
        if _shutdown_requested:
            logger.info("Shutdown requested before round %d", round_num)
            break

        logger.info("=== Backfill round %d / %d ===", round_num, args.max_rounds)
        result = run_backfill(limit=args.limit, batch_size=args.batch_size, dry_run=False)

        total_candidates += result.get("candidates", 0)
        stats = result.get("stats") or {}
        total_analyzed += stats.get("analyzed", 0)
        total_passed += stats.get("passed", 0)
        total_rejected += stats.get("rejected", 0)
        total_skipped += stats.get("skipped", 0)
        total_failed += stats.get("failed", 0)

        if result.get("candidates", 0) == 0 or result.get("shutdown"):
            break

    logger.info(
        "=== Content style backfill finished ===\n"
        "Total candidates: %d | analyzed: %d | passed: %d | rejected: %d | skipped: %d | failed: %d",
        total_candidates,
        total_analyzed,
        total_passed,
        total_rejected,
        total_skipped,
        total_failed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
