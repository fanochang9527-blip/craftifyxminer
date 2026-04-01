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
        assert "IS NULL" not in sql
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
        assert "cs.creator_type IS NULL" in sql

    def test_null_creator_type_excluded_when_partial_selected(self):
        sql, params = build_where_clauses(
            centrality=[],
            creator_types=["vtuber"],
            strategy=[],
            bd_status="all",
            sps_min=0,
            sps_max=100,
        )
        assert "cs.creator_type IS NULL" not in sql
        assert "cs.creator_type = ANY(%s)" in sql

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
