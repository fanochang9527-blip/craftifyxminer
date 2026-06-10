"""Unit tests for scripts.backfill_snapshots_for_scoring."""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from scripts.backfill_snapshots_for_scoring import run_backfill


class TestRunBackfill:
    @patch("scripts.backfill_snapshots_for_scoring.record_snapshot")
    @patch("scripts.backfill_snapshots_for_scoring.upsert_cost")
    @patch("scripts.backfill_snapshots_for_scoring.yaml.safe_load")
    @patch("scripts.backfill_snapshots_for_scoring.ApifyClient")
    @patch("scripts.backfill_snapshots_for_scoring._check_budget")
    @patch("scripts.backfill_snapshots_for_scoring._get_candidates")
    def test_records_apify_cost_and_snapshot(
        self,
        mock_get_candidates,
        mock_check_budget,
        mock_client_class,
        mock_yaml_load,
        mock_upsert_cost,
        mock_record_snapshot,
    ):
        """正常流程：应调用 Apify、记录成本并写入快照。"""
        mock_check_budget.return_value = True
        mock_get_candidates.return_value = [
            {"id": 1, "username": "creator1", "is_seed": False},
        ]
        mock_yaml_load.return_value = {
            "following_actor": {
                "actor_id": "apidojo/twitter-user-scraper",
                "input": {
                    "twitterHandles": [],
                    "getFollowing": True,
                    "getFollowers": False,
                    "maxItems": 500,
                },
            },
        }
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_run = {"id": "run_ref", "defaultDatasetId": "ds_ref", "usageTotalUsd": 0.18}
        mock_client.actor.return_value.call.return_value = mock_run
        mock_dataset = MagicMock()
        mock_dataset.iterate_items.return_value = [
            {
                "author": {
                    "userName": "creator1",
                    "followers": 5000,
                    "friendsCount": 300,
                    "statusesCount": 120,
                }
            }
        ]
        mock_client.dataset.return_value = mock_dataset

        result = run_backfill()

        assert result["run_id"] == "run_ref"
        assert result["candidates"] == 1
        assert result["updated"] == 1
        assert result["budget_ok"] is True
        mock_upsert_cost.assert_called_once()
        call_kwargs = mock_upsert_cost.call_args[1]
        assert call_kwargs["apify_cost_usd"] == 0.18
        mock_record_snapshot.assert_called_once()
        snapshot_kwargs = mock_record_snapshot.call_args[1]
        assert snapshot_kwargs["source"] == "backfill_for_scoring"
        assert snapshot_kwargs["followers"] == 5000

    @patch("scripts.backfill_snapshots_for_scoring._check_budget")
    def test_blocks_when_budget_exceeded(self, mock_check_budget):
        """预算超限时返回 budget_ok=False 且不触发 Apify。"""
        mock_check_budget.return_value = False

        result = run_backfill()

        assert result["budget_ok"] is False
        assert result["candidates"] == 0
        assert result["run_id"] is None

    @patch("scripts.backfill_snapshots_for_scoring._check_budget")
    @patch("scripts.backfill_snapshots_for_scoring._get_candidates")
    def test_no_candidates_returns_empty(self, mock_get_candidates, mock_check_budget):
        """无补算候选人时直接返回空结果。"""
        mock_check_budget.return_value = True
        mock_get_candidates.return_value = []

        result = run_backfill()

        assert result["candidates"] == 0
        assert result["run_id"] is None
        assert result["budget_ok"] is True

    @patch("scripts.backfill_snapshots_for_scoring._check_budget")
    @patch("scripts.backfill_snapshots_for_scoring._get_candidates")
    def test_dry_run_does_not_call_apify(self, mock_get_candidates, mock_check_budget):
        """Dry-run 模式只返回候选人列表，不调用 Apify。"""
        mock_check_budget.return_value = True
        mock_get_candidates.return_value = [
            {"id": 2, "username": "creator2", "is_seed": False},
        ]

        result = run_backfill(dry_run=True)

        assert result["dry_run"] is True
        assert result["candidates"] == 1
        assert result["updated"] == 0
        assert result["budget_ok"] is True
