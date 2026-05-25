"""Tests for BD assignment distribution logic."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth.session import get_bd_distribution_info
from dashboard.candidates_query import build_assigned_count_sql, build_assigned_data_sql


class TestGetBdDistributionInfo:
    def test_single_bd(self):
        with patch("db.connection.fetch_all", return_value=[{"id": 5}]):
            result = get_bd_distribution_info(5)
        assert result == (1, 0)

    def test_multiple_bds(self):
        rows = [{"id": 2}, {"id": 5}, {"id": 7}]
        with patch("db.connection.fetch_all", return_value=rows):
            assert get_bd_distribution_info(2) == (3, 0)
            assert get_bd_distribution_info(5) == (3, 1)
            assert get_bd_distribution_info(7) == (3, 2)

    def test_user_not_found(self):
        rows = [{"id": 2}, {"id": 5}]
        with patch("db.connection.fetch_all", return_value=rows):
            assert get_bd_distribution_info(99) is None

    def test_no_bds(self):
        with patch("db.connection.fetch_all", return_value=[]):
            assert get_bd_distribution_info(1) is None


class TestBuildAssignedCountSql:
    def test_contains_row_number_and_mod_filter(self):
        sql = build_assigned_count_sql("c.is_seed = false", "cs.sps_score DESC", 3, 1)
        assert "ROW_NUMBER() OVER (ORDER BY cs.sps_score DESC)" in sql
        assert "(rn - 1) %% 3 = 1" in sql

    def test_contains_where_clause(self):
        sql = build_assigned_count_sql("c.followers > 500", "cs.sps_score DESC", 2, 0)
        assert "c.followers > 500" in sql

    def test_modulo_zero_for_last_bd(self):
        sql = build_assigned_count_sql("c.is_seed = false", "cs.sps_score DESC", 3, 2)
        assert "(rn - 1) %% 3 = 2" in sql


class TestBuildAssignedDataSql:
    def test_contains_row_number_and_mod_filter(self):
        sql = build_assigned_data_sql("c.is_seed = false", "cs.sps_score DESC", 3, 1)
        assert "ROW_NUMBER() OVER (ORDER BY cs.sps_score DESC)" in sql
        assert "(rn - 1) %% 3 = 1" in sql

    def test_has_limit_offset(self):
        sql = build_assigned_data_sql("c.is_seed = false", "cs.sps_score DESC", 2, 0)
        assert "LIMIT %s OFFSET %s" in sql

    def test_selects_all_required_fields(self):
        sql = build_assigned_data_sql("c.is_seed = false", "cs.sps_score DESC", 2, 0)
        assert "c.id" in sql
        assert "c.username" in sql
        assert "cs.sellability_score" in sql
        assert "cf.audience_score" in sql
        assert "creator_type" in sql

    def test_orders_by_rn(self):
        sql = build_assigned_data_sql("c.is_seed = false", "cs.sps_score DESC", 2, 0)
        assert "ORDER BY rn" in sql

    def test_uses_cte_numbered(self):
        sql = build_assigned_data_sql("c.is_seed = false", "cs.sps_score DESC", 2, 0)
        assert "WITH numbered AS" in sql
        assert "SELECT * FROM numbered" in sql
