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
    current_user_id: int | None = None,
) -> tuple[str, list]:
    """Build WHERE SQL and params from filter selections.

    Returns (where_sql, params).

    当指定 current_user_id 时，只要当前 BD 已经对该创作者做过决策
    （interested / rejected_unfit / rejected_not_creator），就忽略所有业务筛选条件
    （SPS/可卖货/预测销量范围、Centrality、Creator Type、Strategy、bd_status、
    only_sellable、粉丝数阈值等），确保点击决策按钮后该行不会立刻消失。
    仅保留最基础排除条件：非种子创作者、且未因内容风格被 reject。

    要求外层查询已 LEFT JOIN bd_decisions bd ON bd.creator_id = c.id AND bd.user_id = current_user_id。
    """
    # 基础排除条件：永远生效
    base_clauses: list[str] = [
        "c.is_seed = false",
        "c.bd_status != 'content_rejected'",
    ]
    base_params: list = []

    # 业务筛选条件：当前 BD 已决策时可被跳过
    normal_clauses: list[str] = [
        "c.followers > 500",
        "cs.sps_score IS NOT NULL",
        "cs.sps_score BETWEEN %s AND %s",
        "(cs.sellability_score IS NULL OR cs.sellability_score BETWEEN %s AND %s)",
        "(cs.predicted_sales IS NULL OR cs.predicted_sales BETWEEN %s AND %s)",
    ]
    normal_params: list = [sps_min, sps_max, sellability_min, sellability_max, pred_sales_min, pred_sales_max]

    if only_sellable:
        normal_clauses.append("cs.is_sellable = true")

    if centrality:
        if len(centrality) == len(CENTRALITY_OPTS):
            normal_clauses.append("(cs.centrality_tier = ANY(%s) OR cs.centrality_tier IS NULL)")
        else:
            normal_clauses.append("cs.centrality_tier = ANY(%s)")
        normal_params.append(centrality)

    if creator_types:
        if len(creator_types) == len(CREATOR_TYPE_OPTS):
            normal_clauses.append("(COALESCE(c.creator_type_manual, c.creator_type_auto) = ANY(%s) OR (c.creator_type_manual IS NULL AND c.creator_type_auto IS NULL))")
        else:
            normal_clauses.append("COALESCE(c.creator_type_manual, c.creator_type_auto) = ANY(%s)")
        normal_params.append(creator_types)

    if strategy:
        normal_clauses.append("c.discovery_strategy = ANY(%s)")
        normal_params.append(strategy)

    if bd_status != "all":
        normal_clauses.append("c.bd_status = %s")
        normal_params.append(bd_status)

    normal_sql = " AND ".join(normal_clauses)

    if current_user_id is not None:
        where_sql = (
            " AND ".join(base_clauses)
            + f" AND (({normal_sql}) OR (bd.decision IS NOT NULL AND bd.user_id = %s))"
        )
        params = base_params + normal_params + [current_user_id]
    else:
        where_sql = " AND ".join(base_clauses) + f" AND ({normal_sql})"
        params = base_params + normal_params

    return where_sql, params


def calc_pagination(total: int, page: int, per_page: int) -> tuple[int, int]:
    """Return (offset, total_pages) for given pagination state."""
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    return offset, total_pages


def build_assigned_count_sql(
    where_sql: str,
    order_sql: str,
    bd_count: int,
    bd_index: int,
    current_user_id: int | None = None,
) -> str:
    """Build a COUNT query that filters candidates by BD assignment.

    Uses ROW_NUMBER() to enumerate results in the given order, then keeps
    rows where (rn - 1) % bd_count == bd_index (0-based).

    热补丁：当前 BD 自己已经做过决策的行，即使因分数重算被分到其他 BD 的桶里，
    也要被计入并展示，避免点击按钮后条目立刻消失。
    """
    bd_join = ""
    if current_user_id is not None:
        bd_join = f"LEFT JOIN bd_decisions bd ON bd.creator_id = c.id AND bd.user_id = {current_user_id}"
    # 由于 JOIN 条件已经限定 bd.user_id = current_user_id，所以只要 my_decision 非空
    # 即可判定是当前 BD 标记的。
    extra_clause = ""
    if current_user_id is not None:
        extra_clause = " OR (my_decision IS NOT NULL)"
    return f"""
        WITH numbered AS (
            SELECT ROW_NUMBER() OVER (ORDER BY {order_sql}) AS rn,
                   bd.decision AS my_decision
            FROM creators c
            JOIN creator_scores cs ON cs.creator_id = c.id
            LEFT JOIN creator_features cf ON cf.creator_id = c.id
            {bd_join}
            WHERE {where_sql}
        )
        SELECT COUNT(*) AS cnt FROM numbered
        WHERE ((rn - 1) %% {bd_count} = {bd_index}){extra_clause}
    """


def build_assigned_data_sql(
    where_sql: str,
    order_sql: str,
    bd_count: int,
    bd_index: int,
    current_user_id: int | None = None,
) -> str:
    """Build a data query that filters candidates by BD assignment.

    Uses ROW_NUMBER() to enumerate results in the given order, then keeps
    rows where (rn - 1) % bd_count == bd_index (0-based).  The outer query
    orders by rn so pagination is stable.

    热补丁：当前 BD 自己已经做过决策的行，即使因分数重算被分到其他 BD 的桶里，
    也要被查询出来并展示，避免点击按钮后条目立刻消失。
    """
    bd_join = ""
    bd_select = ""
    if current_user_id is not None:
        bd_join = f"LEFT JOIN bd_decisions bd ON bd.creator_id = c.id AND bd.user_id = {current_user_id}"
        bd_select = "bd.decision AS my_decision, bd.note AS my_note,"
    extra_clause = ""
    if current_user_id is not None:
        extra_clause = " OR (my_decision IS NOT NULL)"
    return f"""
        WITH numbered AS (
            SELECT
                c.id, c.username, c.bio, c.followers, c.bd_status, c.bd_decision, c.bd_decision_note,
                c.discovery_strategy, c.has_merch_experience, c.website,
                c.anchor_seed, c.discovered_via, c.discovered_date,
                c.creator_type_manual, c.creator_type_auto,
                COALESCE(c.creator_type_manual, c.creator_type_auto, 'unknown') AS creator_type,
                cs.sellability_score, cs.is_sellable, cs.predicted_sales,
                cs.sps_score, cs.centrality_tier, cs.seed_connections,
                cf.audience_score, cf.engagement_score, cf.virality_score,
                cf.posting_score, cf.monetization_score, cf.growth_score,
                cf.character_consistency, cf.community_score,
                {bd_select}
                ROW_NUMBER() OVER (ORDER BY {order_sql}) AS rn
            FROM creators c
            JOIN creator_scores cs ON cs.creator_id = c.id
            LEFT JOIN creator_features cf ON cf.creator_id = c.id
            {bd_join}
            WHERE {where_sql}
        )
        SELECT * FROM numbered
        WHERE ((rn - 1) %% {bd_count} = {bd_index}){extra_clause}
        ORDER BY rn
        LIMIT %s OFFSET %s
    """
