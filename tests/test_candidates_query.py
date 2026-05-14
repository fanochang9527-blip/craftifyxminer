"""Unit tests for BD 审核工作台 query-building and pagination helpers."""

from dashboard.candidates_query import (
    CENTRALITY_OPTS,
    CREATOR_TYPE_OPTS,
    build_where_clauses,
    calc_pagination,
)


# ---------------------------------------------------------------------------
# Tests — build_where_clauses
# ---------------------------------------------------------------------------

class TestBuildWhereClauses:
    def test_null_centrality_included_when_all_selected(self):
        sql, params = build_where_clauses(
            centrality=list(CENTRALITY_OPTS),
            creator_types=[],
            strategy=[],
            bd_status="all",
            sps_min=0,
            sps_max=100,
        )
        assert "cs.centrality_tier IS NULL" in sql

    def test_null_centrality_excluded_when_partial_selected(self):
        sql, params = build_where_clauses(
            centrality=["Hub"],
            creator_types=[],
            strategy=[],
            bd_status="all",
            sps_min=0,
            sps_max=100,
        )
        assert "cs.centrality_tier IS NULL" not in sql
        assert "cs.centrality_tier = ANY(%s)" in sql

    def test_null_creator_type_included_when_all_selected(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=list(CREATOR_TYPE_OPTS),
            strategy=[],
            bd_status="all",
            sps_min=0,
            sps_max=100,
        )
        assert "COALESCE(c.creator_type_manual, c.creator_type_auto)" in sql
        assert "creator_type_manual IS NULL" in sql

    def test_null_creator_type_excluded_when_partial_selected(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=["vtuber"],
            strategy=[],
            bd_status="all",
            sps_min=0,
            sps_max=100,
        )
        assert "creator_type_manual IS NULL" not in sql
        assert "COALESCE(c.creator_type_manual, c.creator_type_auto) = ANY(%s)" in sql

    def test_bd_status_rejected_unfit(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=[],
            strategy=[],
            bd_status="rejected_unfit",
            sps_min=0,
            sps_max=100,
        )
        assert "c.bd_status = %s" in sql
        assert "rejected_unfit" in params

    def test_bd_status_rejected_not_creator(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=[],
            strategy=[],
            bd_status="rejected_not_creator",
            sps_min=0,
            sps_max=100,
        )
        assert "c.bd_status = %s" in sql
        assert "rejected_not_creator" in params

    def test_bd_status_all_no_filter(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=[],
            strategy=[],
            bd_status="all",
            sps_min=0,
            sps_max=100,
        )
        assert "c.bd_status" not in sql

    def test_bd_status_specific_adds_filter(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=[],
            strategy=[],
            bd_status="ai_passed",
            sps_min=0,
            sps_max=100,
        )
        assert "c.bd_status = %s" in sql
        assert "ai_passed" in params

    def test_sps_range_in_params(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=[],
            strategy=[],
            bd_status="all",
            sps_min=30,
            sps_max=80,
        )
        assert params[0] == 30
        assert params[1] == 80
        assert "BETWEEN %s AND %s" in sql

    def test_strategy_filter(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=[],
            strategy=["seed_following"],
            bd_status="all",
            sps_min=0,
            sps_max=100,
        )
        assert "c.discovery_strategy = ANY(%s)" in sql
        assert ["seed_following"] in params

    def test_only_sellable_filter(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=[],
            strategy=[],
            bd_status="all",
            sps_min=0,
            sps_max=100,
            only_sellable=True,
        )
        assert "cs.is_sellable = true" in sql

    def test_sellability_and_sales_ranges_present(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=[],
            strategy=[],
            bd_status="all",
            sps_min=0,
            sps_max=100,
            sellability_min=40,
            sellability_max=90,
            pred_sales_min=100.0,
            pred_sales_max=800.0,
        )
        assert "cs.sellability_score BETWEEN %s AND %s" in sql
        assert "cs.predicted_sales BETWEEN %s AND %s" in sql
        assert 40 in params and 90 in params
        assert 100.0 in params and 800.0 in params

    def test_followers_min_threshold(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=[],
            strategy=[],
            bd_status="all",
            sps_min=0,
            sps_max=100,
        )
        assert "c.followers > 500" in sql


# ---------------------------------------------------------------------------
# Tests — calc_pagination
# ---------------------------------------------------------------------------

class TestCalcPagination:
    def test_first_page(self):
        offset, total_pages = calc_pagination(total=100, page=1, per_page=20)
        assert offset == 0
        assert total_pages == 5

    def test_middle_page(self):
        offset, total_pages = calc_pagination(total=100, page=3, per_page=20)
        assert offset == 40
        assert total_pages == 5

    def test_last_page(self):
        offset, total_pages = calc_pagination(total=100, page=5, per_page=20)
        assert offset == 80
        assert total_pages == 5

    def test_total_pages_rounds_up(self):
        offset, total_pages = calc_pagination(total=21, page=1, per_page=20)
        assert total_pages == 2

    def test_page_clamped_to_max(self):
        offset, total_pages = calc_pagination(total=50, page=999, per_page=20)
        assert total_pages == 3
        assert offset == 40

    def test_page_clamped_to_min(self):
        offset, total_pages = calc_pagination(total=50, page=0, per_page=20)
        assert offset == 0

    def test_zero_total(self):
        offset, total_pages = calc_pagination(total=0, page=1, per_page=20)
        assert total_pages == 1
        assert offset == 0
