"""Unit tests for pipeline.discovery — anchor rotation & cooldown logic."""

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.discovery import _anchor_priority_and_cooldown, generate_daily_seeds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    rid: int,
    username: str,
    is_seed: bool = False,
    bd_status: str = "pending",
    last_scraped_as_anchor: datetime | None = None,
) -> dict:
    return {
        "id": rid,
        "username": username,
        "is_seed": is_seed,
        "bd_status": bd_status,
        "last_scraped_as_anchor": last_scraped_as_anchor,
    }


def _setup_cursor_mock(mock_get_cursor):
    mock_cursor = MagicMock()
    mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
    mock_get_cursor.return_value.__exit__ = lambda self, *args: False
    return mock_cursor


# ---------------------------------------------------------------------------
# Tests — _anchor_priority_and_cooldown
# ---------------------------------------------------------------------------

class TestAnchorPriorityAndCooldown:
    def test_seed_is_highest_priority(self):
        row = _make_row(1, "seed1", is_seed=True)
        priority, cooldown = _anchor_priority_and_cooldown(row)
        assert priority == 3
        assert cooldown > 0

    def test_interested_is_medium_priority(self):
        row = _make_row(1, "inter1", is_seed=False, bd_status="interested")
        priority, cooldown = _anchor_priority_and_cooldown(row)
        assert priority == 2
        assert cooldown > 0

    def test_rejected_unfit_is_lowest_priority(self):
        row = _make_row(1, "rej1", is_seed=False, bd_status="rejected_unfit")
        priority, cooldown = _anchor_priority_and_cooldown(row)
        assert priority == 1
        assert cooldown > 0


# ---------------------------------------------------------------------------
# Tests — generate_daily_seeds
# ---------------------------------------------------------------------------

class TestGenerateDailySeeds:
    @patch("pipeline.discovery.get_cursor")
    @patch("pipeline.discovery.fetch_all")
    @patch("pipeline.discovery.DAILY_ANCHOR_COUNT", 10)
    @patch("pipeline.discovery.ANCHOR_HIGH_VALUE_COOLDOWN_DAYS", 3)
    @patch("pipeline.discovery.ANCHOR_NORMAL_COOLDOWN_DAYS", 7)
    @patch("pipeline.discovery.ANCHOR_LOW_VALUE_COOLDOWN_DAYS", 14)
    def test_priority_high_value_first(self, mock_fetch_all, mock_get_cursor):
        """High-value (is_seed) anchors should be picked before lower tiers."""
        mock_fetch_all.return_value = [
            _make_row(1, "seed1", is_seed=True, last_scraped_as_anchor=None),
            _make_row(2, "inter1", is_seed=False, bd_status="interested", last_scraped_as_anchor=None),
            _make_row(3, "rej1", is_seed=False, bd_status="rejected_unfit", last_scraped_as_anchor=None),
        ]
        mock_cursor = _setup_cursor_mock(mock_get_cursor)

        anchors = generate_daily_seeds()

        usernames = [a["username"] for a in anchors]
        assert usernames[0] == "seed1"
        assert usernames[1] == "inter1"
        assert usernames[2] == "rej1"
        # Verify last_scraped_as_anchor update was issued
        update_calls = [call for call in mock_cursor.execute.call_args_list if "UPDATE creators" in str(call)]
        assert len(update_calls) == 1

    @patch("pipeline.discovery.get_cursor")
    @patch("pipeline.discovery.fetch_all")
    @patch("pipeline.discovery.DAILY_ANCHOR_COUNT", 1)
    @patch("pipeline.discovery.ANCHOR_HIGH_VALUE_COOLDOWN_DAYS", 3)
    @patch("pipeline.discovery.ANCHOR_NORMAL_COOLDOWN_DAYS", 7)
    @patch("pipeline.discovery.ANCHOR_LOW_VALUE_COOLDOWN_DAYS", 14)
    def test_cooldown_filters_recently_scraped(self, mock_fetch_all, mock_get_cursor):
        """Anchors scanned within their cooldown window should be skipped when eligible anchors suffice."""
        now = datetime.now(timezone.utc)
        mock_fetch_all.return_value = [
            _make_row(1, "seed1", is_seed=True, last_scraped_as_anchor=now - timedelta(days=1)),
            _make_row(2, "seed2", is_seed=True, last_scraped_as_anchor=None),
        ]
        mock_cursor = _setup_cursor_mock(mock_get_cursor)

        anchors = generate_daily_seeds()

        usernames = [a["username"] for a in anchors]
        assert "seed1" not in usernames  # still in 3-day cooldown
        assert usernames[0] == "seed2"

    @patch("pipeline.discovery.get_cursor")
    @patch("pipeline.discovery.fetch_all")
    @patch("pipeline.discovery.DAILY_ANCHOR_COUNT", 10)
    @patch("pipeline.discovery.ANCHOR_HIGH_VALUE_COOLDOWN_DAYS", 3)
    @patch("pipeline.discovery.ANCHOR_NORMAL_COOLDOWN_DAYS", 7)
    @patch("pipeline.discovery.ANCHOR_LOW_VALUE_COOLDOWN_DAYS", 14)
    def test_rotation_by_last_scraped(self, mock_fetch_all, mock_get_cursor):
        """Within the same priority, oldest last_scraped_as_anchor goes first."""
        now = datetime.now(timezone.utc)
        mock_fetch_all.return_value = [
            _make_row(1, "seed1", is_seed=True, last_scraped_as_anchor=now - timedelta(days=10)),
            _make_row(2, "seed2", is_seed=True, last_scraped_as_anchor=now - timedelta(days=5)),
            _make_row(3, "seed3", is_seed=True, last_scraped_as_anchor=None),
        ]
        mock_cursor = _setup_cursor_mock(mock_get_cursor)

        anchors = generate_daily_seeds()

        usernames = [a["username"] for a in anchors]
        # None (never scraped) comes first, then oldest scraped
        assert usernames[0] == "seed3"
        assert usernames[1] == "seed1"
        assert usernames[2] == "seed2"

    @patch("pipeline.discovery.get_cursor")
    @patch("pipeline.discovery.fetch_all")
    @patch("pipeline.discovery.DAILY_ANCHOR_COUNT", 2)
    @patch("pipeline.discovery.ANCHOR_HIGH_VALUE_COOLDOWN_DAYS", 3)
    @patch("pipeline.discovery.ANCHOR_NORMAL_COOLDOWN_DAYS", 7)
    @patch("pipeline.discovery.ANCHOR_LOW_VALUE_COOLDOWN_DAYS", 14)
    def test_cap_respected(self, mock_fetch_all, mock_get_cursor):
        """Should never return more than DAILY_ANCHOR_COUNT anchors."""
        mock_fetch_all.return_value = [
            _make_row(i, f"seed{i}", is_seed=True, last_scraped_as_anchor=None)
            for i in range(1, 11)
        ]
        mock_cursor = _setup_cursor_mock(mock_get_cursor)

        anchors = generate_daily_seeds()

        assert len(anchors) == 2

    @patch("pipeline.discovery.get_cursor")
    @patch("pipeline.discovery.fetch_all")
    @patch("pipeline.discovery.DAILY_ANCHOR_COUNT", 5)
    @patch("pipeline.discovery.ANCHOR_HIGH_VALUE_COOLDOWN_DAYS", 3)
    @patch("pipeline.discovery.ANCHOR_NORMAL_COOLDOWN_DAYS", 7)
    @patch("pipeline.discovery.ANCHOR_LOW_VALUE_COOLDOWN_DAYS", 14)
    def test_fallback_when_cooldown_short(self, mock_fetch_all, mock_get_cursor):
        """If cooldown leaves us short, relax and fill by oldest first."""
        now = datetime.now(timezone.utc)
        mock_fetch_all.return_value = [
            _make_row(1, "seed1", is_seed=True, last_scraped_as_anchor=now - timedelta(days=1)),
            _make_row(2, "seed2", is_seed=True, last_scraped_as_anchor=now - timedelta(days=2)),
            _make_row(3, "seed3", is_seed=True, last_scraped_as_anchor=now - timedelta(days=10)),
        ]
        mock_cursor = _setup_cursor_mock(mock_get_cursor)

        anchors = generate_daily_seeds()

        usernames = [a["username"] for a in anchors]
        # seed3 is outside 3-day cooldown, picked in phase 1
        assert "seed3" in usernames
        # seed1 and seed2 are inside cooldown but used as fallback (oldest first)
        assert len(anchors) == 3
        # fallback fills by oldest first among remaining
        assert usernames.index("seed2") < usernames.index("seed1")

    @patch("pipeline.discovery.get_cursor")
    @patch("pipeline.discovery.fetch_all")
    @patch("pipeline.discovery.DAILY_ANCHOR_COUNT", 10)
    @patch("pipeline.discovery.ANCHOR_HIGH_VALUE_COOLDOWN_DAYS", 3)
    @patch("pipeline.discovery.ANCHOR_NORMAL_COOLDOWN_DAYS", 7)
    @patch("pipeline.discovery.ANCHOR_LOW_VALUE_COOLDOWN_DAYS", 14)
    def test_discovery_batch_inserted(self, mock_fetch_all, mock_get_cursor):
        """A discovery_batches row should be inserted with today's anchors."""
        mock_fetch_all.return_value = [
            _make_row(1, "seed1", is_seed=True, last_scraped_as_anchor=None),
        ]
        mock_cursor = _setup_cursor_mock(mock_get_cursor)

        generate_daily_seeds()

        insert_calls = [call for call in mock_cursor.execute.call_args_list if "INSERT INTO discovery_batches" in str(call)]
        assert len(insert_calls) == 1
        # Check anchor_seeds contains our username
        call_args = insert_calls[0][0]
        assert "seed1" in str(call_args)
