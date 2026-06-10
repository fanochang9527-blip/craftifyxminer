"""Unit tests for scripts.backfill_content_style."""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from scripts.backfill_content_style import (
    _get_backfill_candidates,
    _get_backfill_count,
    run_backfill,
)


class TestGetBackfillCandidates:
    @patch("scripts.backfill_content_style.fetch_all")
    def test_queries_correct_sql(self, mock_fetch_all):
        """应使用正确的 SQL 查询待补算创作者。"""
        mock_fetch_all.return_value = [
            {"id": 1, "username": "creator1"},
            {"id": 2, "username": "creator2"},
        ]

        result = _get_backfill_candidates(limit=100)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["username"] == "creator2"
        mock_fetch_all.assert_called_once()
        call_args = mock_fetch_all.call_args[0]
        assert "LEFT JOIN creator_content_analysis" in call_args[0]
        assert "cca.id IS NULL" in call_args[0]
        assert "bd_status IN ('rule_passed', 'ai_passed')" in call_args[0]
        assert call_args[1] == (100,)


class TestGetBackfillCount:
    @patch("scripts.backfill_content_style.fetch_all")
    def test_returns_count(self, mock_fetch_all):
        """应返回待补算创作者总数。"""
        mock_fetch_all.return_value = [{"cnt": 42}]

        result = _get_backfill_count()

        assert result == 42

    @patch("scripts.backfill_content_style.fetch_all")
    def test_returns_zero_when_empty(self, mock_fetch_all):
        """无结果时应返回 0。"""
        mock_fetch_all.return_value = []

        result = _get_backfill_count()

        assert result == 0


class TestRunBackfill:
    @patch("scripts.backfill_content_style._write_results")
    @patch("scripts.backfill_content_style.ContentStyleFilter")
    @patch("scripts.backfill_content_style._get_backfill_candidates")
    def test_normal_flow(
        self,
        mock_get_candidates,
        mock_filter_cls,
        mock_write_results,
    ):
        """正常流程：应分批分析并写入结果。"""
        mock_get_candidates.return_value = [
            {"id": 1, "username": "creator1"},
            {"id": 2, "username": "creator2"},
        ]
        mock_filter = MagicMock()
        mock_filter.batch_size = 5
        mock_filter_cls.return_value = mock_filter
        mock_filter.filter_batch.return_value = [
            {"creator_id": 1, "status": "analyzed", "passed": True},
            {"creator_id": 2, "status": "analyzed", "passed": False},
        ]
        mock_write_results.return_value = {
            "analyzed": 2, "passed": 1, "rejected": 1, "skipped": 0, "failed": 0
        }

        result = run_backfill(limit=10, batch_size=5)

        assert result["candidates"] == 2
        assert result["batches"] == 1
        assert result["stats"]["analyzed"] == 2
        assert result["dry_run"] is False
        mock_filter.filter_batch.assert_called_once()
        mock_write_results.assert_called_once()

    @patch("scripts.backfill_content_style._get_backfill_candidates")
    def test_no_candidates_returns_empty(self, mock_get_candidates):
        """无候选人时应直接返回空结果。"""
        mock_get_candidates.return_value = []

        result = run_backfill(limit=100)

        assert result["candidates"] == 0
        assert result["batches"] == 0
        assert result["stats"] is None

    @patch("scripts.backfill_content_style._get_backfill_candidates")
    def test_dry_run_does_not_call_llm(self, mock_get_candidates):
        """Dry-run 模式应只查询候选人，不调用 LLM。"""
        mock_get_candidates.return_value = [
            {"id": 1, "username": "creator1"},
        ]

        result = run_backfill(limit=10, dry_run=True)

        assert result["candidates"] == 1
        assert result["dry_run"] is True
        assert result["batches"] == 0
