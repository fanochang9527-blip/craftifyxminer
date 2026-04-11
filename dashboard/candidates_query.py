"""Pure SQL helpers for BD 审核工作台 candidate list (no Streamlit / DB)."""

from __future__ import annotations

import math

CENTRALITY_OPTS = ["Hub", "Connector", "Peripheral"]
CREATOR_TYPE_OPTS = ["oc_creator", "vtuber", "fan_artist", "game_creator", "content_creator", "unknown"]
STRATEGY_OPTS = [
    "seed_following",
    "geo_explore",
    "hashtag_explore",
    "time_explore",
    "legacy",
]
BD_STATUS_OPTS = ["all", "ai_passed", "rule_passed", "pending", "interested", "rejected_unfit", "rejected_not_creator"]


def build_where_clauses(
    *,
    centrality: list[str],
    creator_types: list[str],
    strategy: list[str],
    bd_status: str,
    sps_min: int,
    sps_max: int,
    sellability_min: int = 0,
    sellability_max: int = 100,
    pred_sales_min: float = 0.0,
    pred_sales_max: float = 10000.0,
    only_sellable: bool = False,
) -> tuple[str, list]:
    """Build WHERE SQL and params from filter selections.

    Returns (where_sql, params).
    """
    clauses: list[str] = [
        "c.is_seed = false",
        "cs.sps_score IS NOT NULL",
        "cs.sps_score BETWEEN %s AND %s",
        "(cs.sellability_score IS NULL OR cs.sellability_score BETWEEN %s AND %s)",
        "(cs.predicted_sales IS NULL OR cs.predicted_sales BETWEEN %s AND %s)",
    ]
    params: list = [sps_min, sps_max, sellability_min, sellability_max, pred_sales_min, pred_sales_max]

    if only_sellable:
        clauses.append("cs.is_sellable = true")

    if centrality:
        if len(centrality) == len(CENTRALITY_OPTS):
            clauses.append("(cs.centrality_tier = ANY(%s) OR cs.centrality_tier IS NULL)")
        else:
            clauses.append("cs.centrality_tier = ANY(%s)")
        params.append(centrality)

    if creator_types:
        if len(creator_types) == len(CREATOR_TYPE_OPTS):
            clauses.append("(COALESCE(c.creator_type_manual, c.creator_type_auto) = ANY(%s) OR (c.creator_type_manual IS NULL AND c.creator_type_auto IS NULL))")
        else:
            clauses.append("COALESCE(c.creator_type_manual, c.creator_type_auto) = ANY(%s)")
        params.append(creator_types)

    if strategy:
        clauses.append("c.discovery_strategy = ANY(%s)")
        params.append(strategy)

    if bd_status != "all":
        clauses.append("c.bd_status = %s")
        params.append(bd_status)

    return " AND ".join(clauses), params


def calc_pagination(total: int, page: int, per_page: int) -> tuple[int, int]:
    """Return (offset, total_pages) for given pagination state."""
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    return offset, total_pages
