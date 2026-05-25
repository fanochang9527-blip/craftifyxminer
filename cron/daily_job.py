"""定时任务编排 — APScheduler.

Schedule:
  08:00 — 全链路: 锚点 → L1 扫描 → 深度抓取 → 特征 → Backfill → SPS
  09:00 — 补全 creator_graph 中心度回刷（幂等兜底）
  23:00 — 生成日报数据, 更新成本统计, 种子晋升
"""

import logging
from datetime import date

from apscheduler.schedulers.blocking import BlockingScheduler

from db.connection import fetch_one, get_cursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone="Asia/Shanghai")


@scheduler.scheduled_job("cron", hour=8, minute=0, id="daily_pipeline", misfire_grace_time=7200)
def job_daily_pipeline():
    """Run the full daily pipeline with structured logging."""
    from pipeline.runner import run_full_pipeline
    result = run_full_pipeline()
    logger.info("Daily pipeline finished: %s", result.get("status", "UNKNOWN"))


@scheduler.scheduled_job("cron", hour=9, minute=0, id="backfill_graph", misfire_grace_time=3600)
def job_backfill_graph():
    """Backfill creator_graph from anchor_seed and recalculate centrality tiers."""
    logger.info("=== Job: backfill_graph ===")
    from pipeline.backfill import run_backfill
    result = run_backfill()
    logger.info(
        "Backfill finished: %d edges inserted, %d scores updated",
        result.get("relations_inserted", 0),
        result.get("scores_updated", 0),
    )


@scheduler.scheduled_job("cron", hour=10, minute=0, id="backfill_features", misfire_grace_time=3600)
def job_backfill_features():
    """Backfill creator_features for any creators with tweets but missing features."""
    logger.info("=== Job: backfill_features ===")
    from pipeline.feature_engine import backfill_missing_features
    count = backfill_missing_features()
    logger.info("Backfilled features for %d creators", count)


@scheduler.scheduled_job("cron", hour=23, minute=0, id="daily_summary", misfire_grace_time=21600)
def job_daily_summary():
    """Generate daily summary and ensure cost row exists."""
    logger.info("=== Job: daily_summary ===")
    today = date.today()

    stats = fetch_one(
        """SELECT
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE bd_status IN ('rule_passed', 'ai_passed')) AS passed,
               COUNT(*) FILTER (WHERE bd_status IN ('rule_rejected', 'ai_rejected')) AS rejected
           FROM creators WHERE discovered_date = %s""",
        (today,),
    )
    logger.info("Daily summary for %s: %s", today, dict(stats) if stats else {})

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO cost_tracking (date) VALUES (%s)
               ON CONFLICT (date) DO UPDATE SET
                   total_cost_usd = cost_tracking.apify_cost_usd + cost_tracking.llm_cost_usd + cost_tracking.proxy_cost_usd""",
            (today,),
        )

    from pipeline.evolution import promote_seeds
    promoted = promote_seeds()
    logger.info("Seeds promoted: %d", promoted)


def main():
    logger.info("CraftifyX Miner cron scheduler starting...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
