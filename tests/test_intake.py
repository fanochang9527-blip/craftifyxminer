"""Unit tests for pipeline.intake — filter pipeline & AI result write-back."""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.intake import run_filter_pipeline, store_dataset_items


def _setup_cursor_mock(mock_get_cursor):
    mock_cursor = MagicMock()
    mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
    mock_get_cursor.return_value.__exit__ = lambda self, *args: False
    return mock_cursor


class TestRunFilterPipeline:
    @patch("pipeline.intake.fetch_all")
    @patch("pipeline.intake.get_cursor")
    def test_ai_filter_writes_creator_type_auto(self, mock_get_cursor, mock_fetch_all):
        """AI filter 返回 type 时，应同步写入 creator_type_auto。"""
        mock_cursor = _setup_cursor_mock(mock_get_cursor)

        # 1 pending candidate
        mock_cursor.fetchall.return_value = [
            {"id": 1, "bio": "illustrator | commissions open", "website": ""},
        ]

        # BioRuleFilter returns None -> grey_zone
        with patch(
            "pipeline.bio_rule_filter.BioRuleFilter.filter",
            return_value={"passed": None},
        ):
            # AIFilter returns YES with type
            with patch(
                "pipeline.ai_filter.AIFilter.filter_batch",
                return_value=[
                    {"bio_id": 1, "result": "YES", "type": "oc_creator", "confidence": 0.95},
                ],
            ):
                stats = run_filter_pipeline()

        assert stats["ai_passed"] == 1

        # Find the UPDATE call that writes creator_type_auto
        update_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "UPDATE creators" in str(call.args[0])
        ]
        # One rule update (pending->... actually rule didn't pass/reject so 0) +
        # One AI update
        assert len(update_calls) >= 1
        ai_update = update_calls[-1]
        sql, params = ai_update.args
        assert "creator_type_auto" in sql
        assert params == ("ai_passed", "oc_creator", 1)

    @patch("pipeline.intake.fetch_all")
    @patch("pipeline.intake.get_cursor")
    def test_ai_filter_skips_null_type(self, mock_get_cursor, mock_fetch_all):
        """AI filter 返回 type 为 None 时，不应在 UPDATE 中包含 creator_type_auto。"""
        mock_cursor = _setup_cursor_mock(mock_get_cursor)

        mock_cursor.fetchall.return_value = [
            {"id": 2, "bio": "random bio", "website": ""},
        ]

        with patch(
            "pipeline.bio_rule_filter.BioRuleFilter.filter",
            return_value={"passed": None},
        ):
            with patch(
                "pipeline.ai_filter.AIFilter.filter_batch",
                return_value=[
                    {"bio_id": 2, "result": "NO", "type": None, "confidence": 0.1},
                ],
            ):
                stats = run_filter_pipeline()

        assert stats["ai_rejected"] == 1

        update_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "UPDATE creators" in str(call.args[0])
        ]
        ai_update = update_calls[-1]
        sql, params = ai_update.args
        assert "creator_type_auto" not in sql
        assert params == ("ai_rejected", 2)


class TestStoreDatasetItems:
    @patch("pipeline.intake.get_cursor")
    def test_profile_url_not_written_to_website(self, mock_get_cursor):
        """Twitter/X 主页 URL 不应被写入 creators.website。"""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"is_insert": True, "id": 1}
        mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
        mock_get_cursor.return_value.__exit__ = lambda self, *args: False

        items = [
            {
                "username": "testuser",
                "url": "https://x.com/testuser",
                "followers": 100,
            }
        ]
        store_dataset_items(items)

        insert_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "INSERT INTO creators" in str(call.args[0])
        ]
        assert len(insert_calls) == 1
        sql, params = insert_calls[0].args
        # params: (username, bio, website, followers, following, tweets_count, platform_account_id)
        assert params[2] == "", "Twitter/X profile URL should not be written to creators.website"

    @patch("pipeline.intake.get_cursor")
    def test_explicit_website_is_preserved(self, mock_get_cursor):
        """Apify item 明确提供 website 时应正常写入 creators.website。"""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"is_insert": True, "id": 2}
        mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
        mock_get_cursor.return_value.__exit__ = lambda self, *args: False

        items = [
            {
                "username": "shopuser",
                "url": "https://x.com/shopuser",
                "website": "https://shopuser.booth.pm",
                "followers": 100,
            }
        ]
        store_dataset_items(items)

        insert_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "INSERT INTO creators" in str(call.args[0])
        ]
        assert len(insert_calls) == 1
        sql, params = insert_calls[0].args
        assert params[2] == "https://shopuser.booth.pm"
