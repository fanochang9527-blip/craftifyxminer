"""Tests for pipeline.creator_detail_sync."""

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import pytest

from pipeline.creator_detail_sync import (
    _build_social_links,
    _detect_commission_status,
    _extract_email,
    _extract_links,
    _extract_tags,
    _is_eligible,
    _parse_location,
    sync_creator_detail,
    sync_all_eligible,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_cursor_mock(mock_get_cursor):
    mock_cursor = MagicMock()
    mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
    mock_get_cursor.return_value.__exit__ = lambda self, *args: False
    return mock_cursor


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------

class TestParseLocation:
    def test_empty_location_returns_none(self):
        assert _parse_location(None) == (None, None, None)
        assert _parse_location("") == (None, None, None)

    def test_tokyo_maps_japan(self):
        country, region, loc = _parse_location("Tokyo, Japan")
        assert country == "Japan"
        assert loc == "Tokyo, Japan"

    def test_los_angeles_maps_us(self):
        country, region, loc = _parse_location("Los Angeles, CA")
        assert country == "United States"
        assert region == "CA"
        assert loc == "Los Angeles, CA"

    def test_unknown_city_keeps_location(self):
        country, region, loc = _parse_location("Mars City")
        assert country is None
        assert loc == "Mars City"


class TestExtractLinks:
    def test_extracts_http_urls(self):
        bio = "Shop at https://example.com/shop and https://booth.pm/items/123"
        website = ""
        website_links, merch_links = _extract_links(bio, website)
        assert "https://example.com/shop" in website_links
        assert any("booth.pm" in u for u in website_links)
        assert any("booth.pm" in u for u in merch_links)

    def test_extracts_domain_without_protocol(self):
        bio = "Portfolio: artstation.com/artist"
        website_links, _ = _extract_links(bio, "")
        assert any("artstation.com" in u for u in website_links)

    def test_skips_twitter_short_urls(self):
        bio = "See t.co/abc123"
        website_links, _ = _extract_links(bio, "")
        assert "t.co" not in website_links


class TestExtractEmail:
    def test_extracts_email(self):
        assert _extract_email("Contact me@example.com for work") == "me@example.com"

    def test_no_email_returns_none(self):
        assert _extract_email("No contact info") is None


class TestDetectCommissionStatus:
    def test_open(self):
        assert _detect_commission_status("Commissions open! DM me", []) == "open"

    def test_closed(self):
        assert _detect_commission_status("Commissions closed", []) == "closed"

    def test_waitlist(self):
        assert _detect_commission_status("Waitlist full", []) == "waitlist"

    def test_none(self):
        assert _detect_commission_status("Just posting art", []) is None


class TestExtractTags:
    def test_oc_and_vtuber_tags(self):
        tags, type_tags = _extract_tags(
            "I create my OC and design VTuber models",
            "https://booth.pm/items/123",
            "oc_creator",
        )
        assert "OC" in tags
        assert "VTuber" in tags
        assert "Merch" in tags
        assert "OC" in type_tags  # mapped from oc_creator

    def test_fan_artist_type(self):
        _, type_tags = _extract_tags("", "", "fan_artist")
        assert "Fan Artist" in type_tags


class TestBuildSocialLinks:
    def test_groups_social_domains(self):
        links = ["https://instagram.com/a", "https://booth.pm/items/1", "https://instagram.com/a"]
        social = _build_social_links(links)
        assert social["instagram"] == ["https://instagram.com/a"]
        assert "booth" not in social


class TestIsEligible:
    def test_seed_eligible(self):
        assert _is_eligible({"is_seed": True, "bd_decision": None})

    def test_bd_interested_eligible(self):
        assert _is_eligible({"is_seed": False, "bd_decision": "interested"})

    def test_rejected_ineligible(self):
        assert not _is_eligible({"is_seed": False, "bd_decision": "rejected_unfit"})

    def test_pending_ineligible(self):
        assert not _is_eligible({"is_seed": False, "bd_decision": None})


# ---------------------------------------------------------------------------
# sync_creator_detail tests
# ---------------------------------------------------------------------------

class TestSyncCreatorDetail:
    @patch("pipeline.creator_detail_sync.get_cursor")
    @patch("pipeline.creator_detail_sync.fetch_one")
    def test_ineligible_creator_deletes_detail(self, mock_fetch_one, mock_get_cursor):
        mock_fetch_one.return_value = {"id": 1, "is_seed": False, "bd_decision": None}
        mock_cursor = _setup_cursor_mock(mock_get_cursor)

        result = sync_creator_detail(1, sync_source="test")
        assert result is None
        sql = mock_cursor.execute.call_args[0][0]
        assert "DELETE FROM creators_detail" in sql

    @patch("pipeline.creator_detail_sync.get_cursor")
    @patch("pipeline.creator_detail_sync.fetch_one")
    def test_seed_inserts_detail(self, mock_fetch_one, mock_get_cursor):
        mock_fetch_one.side_effect = [
            {
                "id": 1,
                "is_seed": True,
                "bd_decision": None,
                "bio": "OC artist | Tokyo | https://booth.pm/shop",
                "website": "",
                "followers": 5000,
                "following": 200,
                "tweets_count": 1200,
                "creator_type_manual": "oc_creator",
                "creator_type_auto": "unknown",
                "username": "artist1",
            },
            None,  # content_analysis
        ]
        mock_cursor = _setup_cursor_mock(mock_get_cursor)
        mock_cursor.fetchone.return_value = {"id": 42}

        result = sync_creator_detail(
            1,
            sync_source="test",
            raw_profile={"location": "Tokyo"},
        )
        assert result is not None
        assert result["creator_id"] == 1
        sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO creators_detail" in sql
        payload = mock_cursor.execute.call_args[0][1]
        assert payload["is_seed"] is True
        assert "OC" in payload["tags"]
        assert "https://booth.pm/shop" in payload["website_links"]
        assert payload["country"] == "Japan"


# ---------------------------------------------------------------------------
# sync_all_eligible tests
# ---------------------------------------------------------------------------

class TestSyncAllEligible:
    @patch("pipeline.creator_detail_sync.sync_creator_detail")
    @patch("pipeline.creator_detail_sync.fetch_all")
    def test_processes_all_eligible(self, mock_fetch_all, mock_sync):
        mock_fetch_all.return_value = [{"id": 1}, {"id": 2}]
        mock_sync.return_value = {"creator_id": 1}

        result = sync_all_eligible(sync_source="backfill")
        assert result["total"] == 2
        assert result["synced"] == 2
        assert result["removed"] == 0
