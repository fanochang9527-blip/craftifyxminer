"""定时任务编排 — APScheduler.

Schedule:
  08:00 — 生成当日锚点 (discovery.generate_daily_seeds)
  08:10 — 触发 Apify L1 扫描 (discovery.trigger_l1_scan)
  12:00 — 触发深度抓取 + 指标计算 + SPS 评分
  23:00 — 生成日报数据, 更新成本统计
"""

import logging
from datetime import date

from apscheduler.schedulers.blocking import BlockingScheduler

from db.connection import fetch_one, get_cursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone="Asia/Shanghai")


@scheduler.scheduled_job("cron", hour=8, minute=0, id="generate_anchors")
def job_generate_anchors():
    """Generate daily seed anchors."""
    logger.info("=== Job: generate_daily_seeds ===")
    from pipeline.discovery import generate_daily_seeds
    anchors = generate_daily_seeds()
    logger.info("Generated %d anchors", len(anchors))


@scheduler.scheduled_job("cron", hour=8, minute=10, id="trigger_l1")
def job_trigger_l1():
    """Trigger L1 following scan via Apify."""
    logger.info("=== Job: trigger_l1_scan ===")
    from pipeline.discovery import trigger_l1_scan
    result = trigger_l1_scan()
    logger.info("L1 scan result: %s", result)


@scheduler.scheduled_job("cron", hour=12, minute=0, id="deep_scrape_and_score")
def job_deep_scrape_and_score():
    """Trigger deep scrape, feature computation, and SPS scoring."""
    logger.info("=== Job: deep_scrape + features + SPS ===")
    from pipeline.deep_scrape import trigger_deep_scrape_batch
    from pipeline.feature_engine import compute_all_pending
    from pipeline.sps_scorer import score_all_pending

    ds_result = trigger_deep_scrape_batch()
    logger.info("Deep scrape: %s", ds_result)

    feat_count = compute_all_pending()
    logger.info("Features computed: %d", feat_count)

    score_count = score_all_pending()
    logger.info("Scores computed: %d", score_count)


@scheduler.scheduled_job("cron", hour=23, minute=0, id="daily_summary")
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

    # Ensure cost tracking row exists for today
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO cost_tracking (date) VALUES (%s)
               ON CONFLICT (date) DO UPDATE SET
                   total_cost_usd = cost_tracking.apify_cost_usd + cost_tracking.llm_cost_usd + cost_tracking.proxy_cost_usd""",
            (today,),
        )

    # Run evolution check
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
