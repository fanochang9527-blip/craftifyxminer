"""补算积压数据：清掉 deep scrape 队列，然后补算 features + scores。"""

import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    from db.connection import fetch_one
    from pipeline.deep_scrape import trigger_deep_scrape_batch
    from pipeline.feature_engine import backfill_missing_features
    from pipeline.sps_scorer import score_all_pending
    from pipeline.type_classifier import classify_all_pending

    # 1. 连续 deep scrape 直到清完积压
    round_num = 0
    total_scraped = 0
    while True:
        row = fetch_one(
            """SELECT COUNT(*) as cnt FROM creators
               WHERE bd_status IN ('rule_passed', 'ai_passed')
                 AND NOT EXISTS (
                     SELECT 1 FROM tweets t
                     WHERE t.creator_id = creators.id
                       AND t.collected_at > NOW() - INTERVAL '30 days'
                 )"""
        )
        pending = int(row["cnt"] if row else 0)
        if pending == 0:
            logger.info("Deep scrape backlog cleared.")
            break

        round_num += 1
        logger.info("Round %d: %d candidates pending deep scrape", round_num, pending)
        result = trigger_deep_scrape_batch()
        scraped = result.get("candidates", 0)
        total_scraped += scraped
        logger.info("Round %d complete: scraped %d candidates", round_num, scraped)

        if scraped == 0:
            logger.warning("No candidates scraped in this round, stopping to avoid infinite loop.")
            break

        # 短暂休息，避免过于密集调用 Apify
        time.sleep(5)

    logger.info("Total deep scraped: %d creators", total_scraped)

    # 2. 补算类型分类
    logger.info("Starting type classification backfill...")
    classified = classify_all_pending()
    logger.info("Classified %d creators", classified)

    # 3. 补算 9维特征
    logger.info("Starting feature backfill...")
    features = backfill_missing_features()
    logger.info("Computed features for %d creators", features)

    # 4. 补算 SPS + Sellability 评分
    logger.info("Starting SPS scoring backfill...")
    scores = score_all_pending()
    logger.info("Scored %d creators", scores)

    # 5. 最终统计
    row = fetch_one(
        """SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM tweets t WHERE t.creator_id = creators.id)) as has_tweets,
            COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM creator_features cf WHERE cf.creator_id = creators.id)) as has_features,
            COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM creator_scores cs WHERE cs.creator_id = creators.id AND cs.sps_score IS NOT NULL)) as has_sps
        FROM creators
        WHERE bd_status IN ('ai_passed', 'rule_passed')"""
    )
    logger.info("Final passed pool: total=%d, tweets=%d, features=%d, sps=%d",
                row["total"], row["has_tweets"], row["has_features"], row["has_sps"])


if __name__ == "__main__":
    main()
