"""Tests for pipeline.seed_working_import."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.seed_working_import import _load_usernames, import_seed_working


def _make_xlsx(tmp_path: Path, rows: list[dict]) -> Path:
    xlsx = tmp_path / "seed_working.xlsx"
    pd.DataFrame(rows).to_excel(xlsx, index=False, engine="openpyxl")
    return xlsx


class TestLoadUsernames:
    def test_strips_at_sign_and_lowers(self, tmp_path: Path):
        xlsx = _make_xlsx(tmp_path, [{"username": "@HelloWorld"}, {"username": "TestUser"}])
        assert _load_usernames(xlsx) == ["helloworld", "testuser"]

    def test_skips_empty_and_nan(self, tmp_path: Path):
        xlsx = _make_xlsx(
            tmp_path,
            [{"username": "@foo"}, {"username": ""}, {"username": None}, {"username": "  "}],
        )
        assert _load_usernames(xlsx) == ["foo"]

    def test_missing_username_column_raises(self, tmp_path: Path):
        xlsx = _make_xlsx(tmp_path, [{"handle": "foo"}])
        with pytest.raises(ValueError, match="username"):
            _load_usernames(xlsx)


class TestImportSeedWorking:
    @patch("pipeline.seed_working_import.get_cursor")
    @patch("pipeline.seed_working_import.fetch_all")
    def test_insert_new_creators(self, mock_fetch_all, mock_get_cursor, tmp_path: Path):
        xlsx = _make_xlsx(tmp_path, [{"username": "newuser1"}, {"username": "newuser2"}])
        mock_fetch_all.return_value = []

        mock_cursor = MagicMock()
        mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
        mock_get_cursor.return_value.__exit__ = lambda self, *args: False

        result = import_seed_working(xlsx)

        assert result["total"] == 2
        assert result["inserted"] == 2
        assert result["updated"] == 0

        # Verify INSERT SQL contains expected flags
        calls = [c[0] for c in mock_cursor.execute.call_args_list]
        sqls = [c[0] for c in calls]
        assert any("is_seed = true" in s for s in sqls)
        assert any("bd_decision = 'interested'" in s for s in sqls)
        assert any("seed_working_import" in s for s in sqls)

    @patch("pipeline.seed_working_import.get_cursor")
    @patch("pipeline.seed_working_import.fetch_all")
    def test_update_existing_creators(self, mock_fetch_all, mock_get_cursor, tmp_path: Path):
        xlsx = _make_xlsx(tmp_path, [{"username": "existuser"}])
        mock_fetch_all.return_value = [
            {"id": 42, "username": "existuser", "is_seed": False, "bd_decision": None}
        ]

        mock_cursor = MagicMock()
        mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
        mock_get_cursor.return_value.__exit__ = lambda self, *args: False

        result = import_seed_working(xlsx)

        assert result["total"] == 1
        assert result["inserted"] == 0
        assert result["updated"] == 1

        # Verify UPDATE overwrites discovery_strategy
        calls = [c[0] for c in mock_cursor.execute.call_args_list]
        sql = calls[0][0]
        assert "UPDATE creators" in sql
        assert "discovery_strategy = 'seed_working_import'" in sql

    @patch("pipeline.seed_working_import.get_cursor")
    @patch("pipeline.seed_working_import.fetch_all")
    def test_idempotent_run(self, mock_fetch_all, mock_get_cursor, tmp_path: Path):
        """Running twice on same data should only update, not duplicate."""
        xlsx = _make_xlsx(tmp_path, [{"username": "dupuser"}])

        # First run: insert
        mock_fetch_all.return_value = []
        mock_cursor = MagicMock()
        mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
        mock_get_cursor.return_value.__exit__ = lambda self, *args: False

        result1 = import_seed_working(xlsx)
        assert result1["inserted"] == 1

        # Second run: update
        mock_fetch_all.return_value = [
            {"id": 99, "username": "dupuser", "is_seed": True, "bd_decision": "interested"}
        ]
        result2 = import_seed_working(xlsx)
        assert result2["updated"] == 1
        assert result2["inserted"] == 0
