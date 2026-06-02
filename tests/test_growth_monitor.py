"""Unit tests for pipeline.growth_monitor."""

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import pytest

from pipeline.growth_monitor import (
    calc_growth,
    is_growth_system_mature,
    record_snapshot,
    refresh_growth_scores,
    _PLACEHOLDER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot_row(observed_at: datetime, followers: int) -> dict:
    return {"observed_at": observed_at, "followers": followers}


def _setup_cursor_mock(mock_get_cursor):
    mock_cursor = MagicMock()
    mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
    mock_get_cursor.return_value.__exit__ = lambda self, *args: False
    return mock_cursor


# ---------------------------------------------------------------------------
# Tests — record_snapshot
# ---------------------------------------------------------------------------

class TestRecordSnapshot:
    @patch("pipeline.growth_monitor.get_cursor")
    def test_inserts_into_correct_table(self, mock_get_cursor):
        mock_cursor = _setup_cursor_mock(mock_get_cursor)
        record_snapshot(
            creator_id=1,
            followers=100,
            following=50,
            tweets_count=20,
            source="intake",
            is_seed=False,
        )
        sql = mock_cursor.execute.call_args[0][0]
        assert "creator_snapshots" in sql
        assert "ON CONFLICT" in sql

    @patch("pipeline.growth_monitor.get_cursor")
    def test_seed_goes_to_seed_table(self, mock_get_cursor):
        mock_cursor = _setup_cursor_mock(mock_get_cursor)
        record_snapshot(
            creator_id=1,
            followers=100,
            following=50,
            tweets_count=20,
            source="seed_import",
            is_seed=True,
        )
        sql = mock_cursor.execute.call_args[0][0]
        assert "seed_follower_snapshots" in sql


# ---------------------------------------------------------------------------
# Tests — calc_growth
# ---------------------------------------------------------------------------

class TestCalcGrowth:
    @patch("pipeline.growth_monitor.fetch_all")
    def test_zero_snapshots_returns_placeholder(self, mock_fetch_all):
        mock_fetch_all.return_value = []
        score, is_real = calc_growth(1)
        assert score == _PLACEHOLDER
        assert is_real is False

    @patch("pipeline.growth_monitor.fetch_all")
    def test_one_snapshot_returns_placeholder(self, mock_fetch_all):
        mock_fetch_all.return_value = [
            _make_snapshot_row(datetime.now(timezone.utc) - timedelta(days=5), 100),
        ]
        score, is_real = calc_growth(1)
        assert score == _PLACEHOLDER
        assert is_real is False

    @patch("pipeline.growth_monitor.fetch_all")
    def test_two_snapshots_under_30_days_returns_placeholder(self, mock_fetch_all):
        now = datetime.now(timezone.utc)
        mock_fetch_all.return_value = [
            _make_snapshot_row(now - timedelta(days=10), 100),
            _make_snapshot_row(now, 120),
        ]
        score, is_real = calc_growth(1)
        assert score == _PLACEHOLDER
        assert is_real is False

    @patch("pipeline.growth_monitor.fetch_all")
    def test_two_snapshots_over_30_days_returns_real(self, mock_fetch_all):
        now = datetime.now(timezone.utc)
        mock_fetch_all.return_value = [
            _make_snapshot_row(now - timedelta(days=35), 100),
            _make_snapshot_row(now, 120),
        ]
        score, is_real = calc_growth(1)
        assert is_real is True
        # growth_rate = 20/100 = 0.2, score = 50 + 20 = 70
        assert score == 70.0

    @patch("pipeline.growth_monitor.fetch_all")
    def test_20_percent_growth(self, mock_fetch_all):
        now = datetime.now(timezone.utc)
        mock_fetch_all.return_value = [
            _make_snapshot_row(now - timedelta(days=30), 100),
            _make_snapshot_row(now, 120),
        ]
        score, is_real = calc_growth(1)
        assert is_real is True
        assert score == 70.0

    @patch("pipeline.growth_monitor.fetch_all")
    @patch("pipeline.growth_monitor.get_cursor")
    def test_sudden_drop_anomaly(self, mock_get_cursor, mock_fetch_all):
        now = datetime.now(timezone.utc)
        mock_fetch_all.return_value = [
            _make_snapshot_row(now - timedelta(days=35), 2000),
            _make_snapshot_row(now, 100),
        ]
        mock_cursor = _setup_cursor_mock(mock_get_cursor)
        score, is_real = calc_growth(1)
        # 90% drop, anomaly triggered, no fallback row → placeholder
        assert score == _PLACEHOLDER
        assert is_real is False
        # Verify anomaly was marked
        sql = mock_cursor.execute.call_args[0][0]
        assert "anomaly_type = 'sudden_drop'" in sql

    @patch("pipeline.growth_monitor.fetch_all")
    @patch("pipeline.growth_monitor.get_cursor")
    def test_sudden_drop_with_fallback(self, mock_get_cursor, mock_fetch_all):
        now = datetime.now(timezone.utc)
        mock_fetch_all.return_value = [
            _make_snapshot_row(now - timedelta(days=60), 2000),
            _make_snapshot_row(now - timedelta(days=30), 1900),
            _make_snapshot_row(now, 100),
        ]
        mock_cursor = _setup_cursor_mock(mock_get_cursor)
        score, is_real = calc_growth(1)
        # Fallback to row[-2] (1900 → 100), days = 30, growth = -1800/1900 ≈ -0.947
        # score = 50 - 94.7 = -44.7 → clamped to 0
        assert is_real is True
        assert score == 0.0


# ---------------------------------------------------------------------------
# Tests — refresh_growth_scores
# ---------------------------------------------------------------------------

class TestRefreshGrowthScores:
    @patch("pipeline.growth_monitor.fetch_all")
    @patch("pipeline.growth_monitor.fetch_one")
    @patch("pipeline.growth_monitor.get_cursor")
    @patch("pipeline.growth_monitor._update_growth_and_infer")
    def test_only_updates_placeholder(
        self, mock_update, mock_get_cursor, mock_fetch_one, mock_fetch_all
    ):
        now = datetime.now(timezone.utc)
        # fetch_all calls:
        # 1. creator_snapshots eligible query
        # 2. calc_growth internal snapshot query
        # 3. seed_follower_snapshots eligible query
        mock_fetch_all.side_effect = [
            [{"creator_id": 1, "first_at": now - timedelta(days=35), "last_at": now}],
            [
                {"observed_at": now - timedelta(days=35), "followers": 100},
                {"observed_at": now, "followers": 120},
            ],
            [],
        ]
        # fetch_one calls:
        # 1. current growth_score check in creator loop
        mock_fetch_one.return_value = {"growth_score": 50.0}
        _setup_cursor_mock(mock_get_cursor)

        result = refresh_growth_scores()
        assert result["checked"] == 1
        assert result["graduated"] == 1
        mock_update.assert_called_once()

    @patch("pipeline.growth_monitor.fetch_all")
    @patch("pipeline.growth_monitor.fetch_one")
    @patch("pipeline.growth_monitor.get_cursor")
    @patch("pipeline.growth_monitor._update_growth_and_infer")
    def test_skips_already_real(
        self, mock_update, mock_get_cursor, mock_fetch_one, mock_fetch_all
    ):
        now = datetime.now(timezone.utc)
        # fetch_all calls:
        # 1. creator_snapshots eligible query
        # 2. seed_follower_snapshots eligible query
        # (calc_growth is skipped because growth_score != 50.0)
        mock_fetch_all.side_effect = [
            [{"creator_id": 1, "first_at": now - timedelta(days=35), "last_at": now}],
            [],
        ]
        # growth_score already real (not 50.0)
        mock_fetch_one.return_value = {"growth_score": 70.0}
        _setup_cursor_mock(mock_get_cursor)

        result = refresh_growth_scores()
        assert result["checked"] == 1
        assert result["graduated"] == 0
        mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — is_growth_system_mature
# ---------------------------------------------------------------------------

class TestIsGrowthSystemMature:
    @patch("pipeline.growth_monitor.fetch_one")
    def test_no_snapshots_returns_false(self, mock_fetch_one):
        mock_fetch_one.return_value = {"start_date": None}
        assert is_growth_system_mature() is False

    @patch("pipeline.growth_monitor.fetch_one")
    def test_under_30_days_returns_false(self, mock_fetch_one):
        mock_fetch_one.return_value = {
            "start_date": datetime.now(timezone.utc) - timedelta(days=15)
        }
        assert is_growth_system_mature() is False

    @patch("pipeline.growth_monitor.fetch_one")
    def test_over_30_days_returns_true(self, mock_fetch_one):
        mock_fetch_one.return_value = {
            "start_date": datetime.now(timezone.utc) - timedelta(days=35)
        }
        assert is_growth_system_mature() is True
