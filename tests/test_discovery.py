"""Unit tests for pipeline.discovery — anchor rotation & cooldown logic."""

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.discovery import _anchor_priority_and_cooldown, generate_daily_seeds, trigger_l1_scan


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


# ---------------------------------------------------------------------------
# Tests — trigger_l1_scan actor switching
# ---------------------------------------------------------------------------

class TestTriggerL1ScanActorSwitching:
    @patch("pipeline.discovery.upsert_cost")
    @patch("pipeline.discovery.yaml.safe_load")
    @patch("pipeline.discovery.ApifyClient")
    @patch("pipeline.discovery.APIFY_L1_ACTOR", "alt")
    @patch("pipeline.discovery.fetch_one")
    def test_uses_alt_following_actor_when_configured(self, mock_fetch_one, mock_client_class, mock_yaml_load, mock_upsert_cost):
        """当 APIFY_L1_ACTOR=alt 时，应使用 alt_following_actor 配置。"""
        mock_fetch_one.return_value = {"today_cost": 0.0}
        mock_yaml_load.return_value = {
            "alt_following_actor": {
                "actor_id": "get-leads/all-in-one-x-scraper",
                "input": {"mode": "following", "usernames": [], "maxResults": 500},
            },
            "following_actor": {
                "actor_id": "apidojo/twitter-user-scraper",
                "input": {"twitterHandles": [], "getFollowing": True, "maxItems": 500},
            },
        }
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_run = {"id": "run123", "defaultDatasetId": "ds123", "usageTotalUsd": 0.32}
        mock_client.actor.return_value.call.return_value = mock_run
        mock_dataset = MagicMock()
        mock_dataset.iterate_items.return_value = []
        mock_client.dataset.return_value = mock_dataset

        result = trigger_l1_scan(
            anchors=[{"username": "testuser", "strategy": "seed_following", "seed_id": 1}]
        )

        mock_client.actor.assert_called_once_with("get-leads/all-in-one-x-scraper")
        call_input = mock_client.actor.return_value.call.call_args[1]["run_input"]
        assert call_input["mode"] == "following"
        assert call_input["usernames"] == ["testuser"]
        assert call_input["maxResults"] == 500
        assert result["run_id"] == "run123"
        mock_upsert_cost.assert_called_once()
        call_kwargs = mock_upsert_cost.call_args[1]
        assert call_kwargs["apify_cost_usd"] == 0.32

    @patch("pipeline.discovery.upsert_cost")
    @patch("pipeline.discovery.yaml.safe_load")
    @patch("pipeline.discovery.ApifyClient")
    @patch("pipeline.discovery.APIFY_L1_ACTOR", "apidojo")
    @patch("pipeline.discovery.fetch_one")
    def test_uses_default_following_actor(self, mock_fetch_one, mock_client_class, mock_yaml_load, mock_upsert_cost):
        """当 APIFY_L1_ACTOR=apidojo（默认）时，应使用 following_actor 配置。"""
        mock_fetch_one.return_value = {"today_cost": 0.0}
        mock_yaml_load.return_value = {
            "alt_following_actor": {
                "actor_id": "get-leads/all-in-one-x-scraper",
                "input": {"mode": "following", "usernames": [], "maxResults": 500},
            },
            "following_actor": {
                "actor_id": "apidojo/twitter-user-scraper",
                "input": {"twitterHandles": [], "getFollowing": True, "maxItems": 500},
            },
        }
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_run = {"id": "run456", "defaultDatasetId": "ds456", "usageTotalUsd": 0.35}
        mock_client.actor.return_value.call.return_value = mock_run
        mock_dataset = MagicMock()
        mock_dataset.iterate_items.return_value = []
        mock_client.dataset.return_value = mock_dataset

        result = trigger_l1_scan(
            anchors=[{"username": "testuser", "strategy": "seed_following", "seed_id": 1}]
        )

        mock_client.actor.assert_called_once_with("apidojo/twitter-user-scraper")
        call_input = mock_client.actor.return_value.call.call_args[1]["run_input"]
        assert call_input["twitterHandles"] == ["testuser"]
        assert call_input["maxItems"] == 500
        assert result["run_id"] == "run456"
        mock_upsert_cost.assert_called_once()
        call_kwargs = mock_upsert_cost.call_args[1]
        assert call_kwargs["apify_cost_usd"] == 0.35
