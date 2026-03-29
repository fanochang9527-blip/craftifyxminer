"""内部 REST API — 手动触发深度抓取、查询状态等。"""

import logging
from datetime import date

from flask import Blueprint, request, jsonify

from auth.decorators import admin_required, login_required
from db.connection import fetch_all, fetch_one

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/trigger-deep-scrape", methods=["POST"])
@admin_required
def trigger_deep_scrape():
    """Trigger deep scrape for creators that passed AI filter."""
    from pipeline.deep_scrape import trigger_deep_scrape_batch

    limit = request.json.get("limit", 50) if request.json else 50
    result = trigger_deep_scrape_batch(limit=limit)
    return jsonify(result)


@api_bp.route("/daily-stats")
@login_required
def daily_stats():
    """Return today's discovery pipeline statistics."""
    today = date.today().isoformat()
    stats = fetch_one(
        """SELECT
               COUNT(*) FILTER (WHERE discovered_date = %s) AS today_discovered,
               COUNT(*) FILTER (WHERE bd_status = 'rule_passed' AND discovered_date = %s) AS rule_passed,
               COUNT(*) FILTER (WHERE bd_status = 'ai_passed' AND discovered_date = %s) AS ai_passed,
               COUNT(*) FILTER (WHERE bd_status = 'rule_rejected' AND discovered_date = %s) AS rule_rejected,
               COUNT(*) FILTER (WHERE bd_status = 'ai_rejected' AND discovered_date = %s) AS ai_rejected
           FROM creators""",
        (today, today, today, today, today),
    )
    return jsonify(dict(stats) if stats else {})


@api_bp.route("/cost-summary")
@login_required
def cost_summary():
    """Return cost tracking for today and month-to-date."""
    today_row = fetch_one(
        "SELECT * FROM cost_tracking WHERE date = CURRENT_DATE"
    )
    mtd_row = fetch_one(
        """SELECT
               SUM(apify_cost_usd) AS mtd_apify,
               SUM(llm_cost_usd) AS mtd_llm,
               SUM(proxy_cost_usd) AS mtd_proxy,
               SUM(total_cost_usd) AS mtd_total
           FROM cost_tracking
           WHERE date >= date_trunc('month', CURRENT_DATE)"""
    )
    return jsonify({
        "today": dict(today_row) if today_row else {},
        "month_to_date": dict(mtd_row) if mtd_row else {},
    })
