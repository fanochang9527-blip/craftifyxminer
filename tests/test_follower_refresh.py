"""Unit tests for pipeline.follower_refresh — budget check & cost tracking."""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.follower_refresh import run_follower_refresh


class TestRunFollowerRefresh:
    @patch("pipeline.follower_refresh.record_snapshot")
    @patch("pipeline.follower_refresh.upsert_cost")
    @patch("pipeline.follower_refresh.yaml.safe_load")
    @patch("pipeline.follower_refresh.ApifyClient")
    @patch("pipeline.follower_refresh._check_budget")
    @patch("pipeline.follower_refresh._get_refresh_candidates")
    def test_records_apify_cost(self, mock_get_candidates, mock_check_budget, mock_client_class, mock_yaml_load, mock_upsert_cost, mock_record_snapshot):
        """Apify run 完成后应记录 usageTotalUsd 到 cost_tracking。"""
        mock_check_budget.return_value = True
        mock_get_candidates.return_value = [
            {"id": 1, "username": "seed1", "is_seed": True},
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
        mock_run = {"id": "run_ref", "defaultDatasetId": "ds_ref", "usageTotalUsd": 0.396}
        mock_client.actor.return_value.call.return_value = mock_run
        mock_dataset = MagicMock()
        mock_dataset.iterate_items.return_value = [
            {
                "author": {
                    "userName": "seed1",
                    "followers": 10000,
                    "friendsCount": 500,
                    "statusesCount": 200,
                }
            }
        ]
        mock_client.dataset.return_value = mock_dataset

        result = run_follower_refresh()

        assert result["run_id"] == "run_ref"
        mock_upsert_cost.assert_called_once()
        call_kwargs = mock_upsert_cost.call_args[1]
        assert call_kwargs["apify_cost_usd"] == 0.396

    @patch("pipeline.follower_refresh._check_budget")
    def test_blocks_when_budget_exceeded(self, mock_check_budget):
        """预算超限时返回 budget_ok=False 且不触发 Apify。"""
        mock_check_budget.return_value = False

        result = run_follower_refresh()

        assert result["budget_ok"] is False
        assert result["candidates"] == 0
        assert result["run_id"] is None

    @patch("pipeline.follower_refresh._check_budget")
    @patch("pipeline.follower_refresh._get_refresh_candidates")
    def test_no_candidates_returns_empty(self, mock_get_candidates, mock_check_budget):
        """无刷新候选人时直接返回空结果。"""
        mock_check_budget.return_value = True
        mock_get_candidates.return_value = []

        result = run_follower_refresh()

        assert result["candidates"] == 0
        assert result["run_id"] is None
        assert result["budget_ok"] is True
