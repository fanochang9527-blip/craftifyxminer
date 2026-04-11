"""飞轮进化 (简化版) — 数据回流 + Seed 自动晋升。

当 sales_feedback.gmv > $1000 时将对应创作者晋升为 Seed。
月度报告: 按 creator_type 统计联系成功率、成交率。
"""

import logging
from datetime import date, timedelta

from db.connection import execute, fetch_all, get_cursor

logger = logging.getLogger(__name__)

GMV_THRESHOLD = 1000.0


def promote_seeds() -> int:
    """Promote creators with total GMV > threshold to Seed status.

    Returns the number of newly promoted seeds.
    """
    candidates = fetch_all(
        """SELECT sf.creator_id, SUM(sf.gmv) AS total_gmv
           FROM sales_feedback sf
           JOIN creators c ON c.id = sf.creator_id
           WHERE c.is_seed = false
           GROUP BY sf.creator_id
           HAVING SUM(sf.gmv) > %s""",
        (GMV_THRESHOLD,),
    )

    promoted = 0
    for row in candidates:
        with get_cursor() as cur:
            cur.execute(
                "UPDATE creators SET is_seed = true WHERE id = %s AND is_seed = false",
                (row["creator_id"],),
            )
            if cur.rowcount > 0:
                promoted += 1
                logger.info(
                    "Promoted creator %d to Seed with GMV $%.2f",
                    row["creator_id"], float(row["total_gmv"]),
                )

    if promoted:
        logger.info("Total seeds promoted this run: %d", promoted)
    return promoted


def monthly_report() -> dict:
    """Generate monthly performance report by creator_type.

    Returns a dict with type-level stats:
        {type: {total, contacted, responded, deals_closed, total_gmv, contact_rate, deal_rate}}
    """
    first_of_month = date.today().replace(day=1)

    rows = fetch_all(
        """SELECT
               COALESCE(c.creator_type_manual, c.creator_type_auto, 'unknown') AS ctype,
               COUNT(DISTINCT c.id) AS total,
               COUNT(DISTINCT ol.creator_id) AS contacted,
               COUNT(DISTINCT ol.creator_id) FILTER (WHERE ol.response_received = true) AS responded,
               COUNT(DISTINCT sf.creator_id) AS deals_closed,
               COALESCE(SUM(sf.gmv), 0) AS total_gmv
           FROM creators c
           LEFT JOIN outreach_log ol ON ol.creator_id = c.id AND ol.contacted_at >= %s
           LEFT JOIN sales_feedback sf ON sf.creator_id = c.id AND sf.created_at >= %s
           WHERE c.is_seed = true
           GROUP BY ctype
           ORDER BY ctype""",
        (first_of_month, first_of_month),
    )

    report = {}
    for row in rows:
        ctype = row["ctype"] or "unknown"
        total = int(row["total"])
        contacted = int(row["contacted"])
        deals = int(row["deals_closed"])
        report[ctype] = {
            "total": total,
            "contacted": contacted,
            "responded": int(row["responded"]),
            "deals_closed": deals,
            "total_gmv": float(row["total_gmv"]),
            "contact_rate": contacted / total if total > 0 else 0,
            "deal_rate": deals / contacted if contacted > 0 else 0,
        }

    logger.info("Monthly report: %s", report)
    return report
