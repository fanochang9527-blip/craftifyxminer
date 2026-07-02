"""定时任务编排 — APScheduler.

Schedule:
  00:00 — 全链路: 锚点 → L1 扫描 → 深度抓取 → 特征 → Backfill → SPS
  01:00 — 补全 creator_graph 中心度回刷（幂等兜底）
  02:00 — 补算有 tweets 但缺失特征的 creator_features
  03:00 — 将 placeholder growth_score 转正为真实值
  22:00 — 生成日报数据, 更新成本统计, 种子晋升
  23:00 — 种子 / BD interested 创作者粉丝数刷新
"""

import logging
from datetime import date

from apscheduler.schedulers.blocking import BlockingScheduler

from db.connection import fetch_one, get_cursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone="Asia/Shanghai")


@scheduler.scheduled_job("cron", hour=0, minute=0, id="daily_pipeline", misfire_grace_time=7200)
def job_daily_pipeline():
    """Run the full daily pipeline with structured logging."""
    from pipeline.runner import run_full_pipeline
    result = run_full_pipeline()
    logger.info("Daily pipeline finished: %s", result.get("status", "UNKNOWN"))


@scheduler.scheduled_job("cron", hour=1, minute=0, id="backfill_graph", misfire_grace_time=3600)
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


@scheduler.scheduled_job("cron", hour=2, minute=0, id="backfill_features", misfire_grace_time=3600)
def job_backfill_features():
    """Backfill creator_features for any creators with tweets but missing features."""
    logger.info("=== Job: backfill_features ===")
    from pipeline.feature_engine import backfill_missing_features
    count = backfill_missing_features()
    logger.info("Backfilled features for %d creators", count)


@scheduler.scheduled_job("cron", hour=22, minute=0, id="daily_summary", misfire_grace_time=21600)
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


@scheduler.scheduled_job("cron", hour=23, minute=0, id="follower_refresh", misfire_grace_time=3600)
def job_follower_refresh():
    """Periodic follower refresh for seeds and interested creators (every 3 days per creator)."""
    logger.info("=== Job: follower_refresh ===")
    from pipeline.follower_refresh import run_follower_refresh

    result = run_follower_refresh()
    logger.info(
        "Follower refresh finished: %d candidates, %d updated",
        result.get("candidates", 0),
        result.get("updated", 0),
    )


@scheduler.scheduled_job("cron", hour=3, minute=0, id="growth_monitor", misfire_grace_time=3600)
def job_growth_monitor():
    """Graduate placeholder growth scores to real values after 30 days of history."""
    logger.info("=== Job: growth_monitor ===")
    from pipeline.growth_monitor import refresh_growth_scores

    result = refresh_growth_scores()
    logger.info(
        "Growth refresh finished: %d checked, %d graduated",
        result.get("checked", 0),
        result.get("graduated", 0),
    )


def main():
    logger.info("CraftifyX Miner cron scheduler starting...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
