"""Pure SQL helpers for BD 审核工作台 candidate list (no Streamlit / DB)."""

from __future__ import annotations

import math

CENTRALITY_OPTS = ["Hub", "Connector", "Peripheral"]
CREATOR_TYPE_OPTS = ["oc_creator", "vtuber", "fan_artist", "game_creator", "content_creator"]
STRATEGY_OPTS = ["seed_following", "geo_explore", "hashtag_explore", "time_explore"]
BD_STATUS_OPTS = ["all", "ai_passed", "rule_passed", "pending", "interested", "rejected", "deferred"]


def build_where_clauses(
    *,
    centrality: list[str],
    creator_types: list[str],
    strategy: list[str],
    bd_status: str,
    sps_min: int,
    sps_max: int,
) -> tuple[str, list]:
    """Build WHERE SQL and params from filter selections.

    Returns (where_sql, params).
    """
    clauses: list[str] = [
        "c.is_seed = false",
        "cs.sps_score IS NOT NULL",
        "cs.sps_score BETWEEN %s AND %s",
    ]
    params: list = [sps_min, sps_max]

    if centrality:
        if len(centrality) == len(CENTRALITY_OPTS):
            clauses.append("(cs.centrality_tier = ANY(%s) OR cs.centrality_tier IS NULL)")
        else:
            clauses.append("cs.centrality_tier = ANY(%s)")
        params.append(centrality)

    if creator_types:
        if len(creator_types) == len(CREATOR_TYPE_OPTS):
            clauses.append("(cs.creator_type = ANY(%s) OR cs.creator_type IS NULL)")
        else:
            clauses.append("cs.creator_type = ANY(%s)")
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
