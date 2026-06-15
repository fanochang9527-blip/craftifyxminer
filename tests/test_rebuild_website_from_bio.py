"""Unit tests for scripts.rebuild_website_from_bio."""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from scripts.rebuild_website_from_bio import (
    extract_links,
    is_link_aggregator_url,
    is_merch_url,
    is_social_url,
    pick_website,
    rebuild_website_from_bio,
)


class TestExtractLinks:
    def test_extracts_http_url(self):
        assert extract_links("Shop: https://booth.pm/shop") == ["https://booth.pm/shop"]

    def test_extracts_multiple_urls(self):
        bio = "Portfolio: https://artstation.com/artist Shop: https://booth.pm/shop"
        links = extract_links(bio)
        assert "https://artstation.com/artist" in links
        assert "https://booth.pm/shop" in links

    def test_deduplicates(self):
        bio = "https://booth.pm/shop and https://booth.pm/shop"
        assert extract_links(bio) == ["https://booth.pm/shop"]

    def test_adds_https_prefix(self):
        bio = "Shop: booth.pm/shop"
        assert extract_links(bio) == ["https://booth.pm/shop"]

    def test_empty_bio(self):
        assert extract_links("") == []
        assert extract_links(None) == []


class TestUrlClassification:
    def test_twitter_is_social(self):
        assert is_social_url("https://twitter.com/user")
        assert is_social_url("https://x.com/user")
        assert is_social_url("https://t.co/abc123")

    def test_instagram_is_social(self):
        assert is_social_url("https://instagram.com/user")

    def test_bilibili_is_social(self):
        assert is_social_url("https://bilibili.com/user")

    def test_booth_is_merch(self):
        assert is_merch_url("https://booth.pm/shop")

    def test_etsy_is_merch(self):
        assert is_merch_url("https://etsy.com/shop/name")

    def test_linktree_is_aggregator(self):
        assert is_link_aggregator_url("https://linktr.ee/user")

    def test_artstation_is_not_social(self):
        assert not is_social_url("https://artstation.com/artist")


class TestPickWebsite:
    def test_prefers_merch_over_portfolio(self):
        links = [
            "https://artstation.com/artist",
            "https://booth.pm/shop",
            "https://twitter.com/user",
        ]
        assert pick_website(links) == "https://booth.pm/shop"

    def test_prefers_aggregator_when_no_merch(self):
        links = [
            "https://artstation.com/artist",
            "https://linktr.ee/user",
            "https://twitter.com/user",
        ]
        assert pick_website(links) == "https://linktr.ee/user"

    def test_prefers_portfolio_when_no_merch_or_aggregator(self):
        links = [
            "https://twitter.com/user",
            "https://artstation.com/artist",
        ]
        assert pick_website(links) == "https://artstation.com/artist"

    def test_falls_back_to_first_non_social(self):
        links = [
            "https://twitter.com/user",
            "https://example.com/portfolio",
        ]
        assert pick_website(links) == "https://example.com/portfolio"

    def test_all_social_returns_none(self):
        links = ["https://twitter.com/user", "https://instagram.com/user"]
        assert pick_website(links) is None

    def test_empty_returns_none(self):
        assert pick_website([]) is None


class TestRebuildWebsiteFromBio:
    @patch("scripts.rebuild_website_from_bio.get_cursor")
    @patch("scripts.rebuild_website_from_bio.fetch_all")
    @patch("scripts.rebuild_website_from_bio.compute_features_for_creator")
    def test_rebuild_and_recompute(
        self, mock_compute, mock_fetch_all, mock_get_cursor
    ):
        mock_fetch_all.return_value = [
            {"id": 1, "username": "a", "bio": "Shop: https://booth.pm/shop", "website": "https://twitter.com/a"},
            {"id": 2, "username": "b", "bio": "Only twitter https://x.com/b", "website": "https://x.com/b"},
            {"id": 3, "username": "c", "bio": "No links at all", "website": "https://x.com/c"},
        ]
        mock_cursor = MagicMock()
        mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
        mock_get_cursor.return_value.__exit__ = lambda self, *args: False

        stats = rebuild_website_from_bio(dry_run=False, recompute=True)

        # 3 rows fetched; id=1 updated to booth, id=2 cleared, id=3 cleared (no links in bio)
        assert stats["updated"] == 3
        assert stats["recomputed"]["success"] == 3

        # Verify executemany update
        executemany_calls = [
            call for call in mock_cursor.method_calls if call[0] == "executemany"
        ]
        assert len(executemany_calls) == 1
        sql, params = executemany_calls[0].args
        assert "UPDATE creators SET website" in sql
        param_by_id = {p[1]: p[0] for p in params}
        assert param_by_id[1] == "https://booth.pm/shop"
        assert param_by_id[2] == ""
        assert param_by_id[3] == ""

    @patch("scripts.rebuild_website_from_bio.get_cursor")
    @patch("scripts.rebuild_website_from_bio.fetch_all")
    @patch("scripts.rebuild_website_from_bio.compute_features_for_creator")
    def test_dry_run_does_not_write(
        self, mock_compute, mock_fetch_all, mock_get_cursor
    ):
        mock_fetch_all.return_value = [
            {"id": 1, "username": "a", "bio": "Shop: https://booth.pm/shop", "website": ""},
        ]
        mock_cursor = MagicMock()
        mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
        mock_get_cursor.return_value.__exit__ = lambda self, *args: False

        stats = rebuild_website_from_bio(dry_run=True, recompute=True)

        assert stats["updated"] == 0
        assert stats["recomputed"]["success"] == 0
        mock_cursor.execute.assert_not_called()
        mock_cursor.executemany.assert_not_called()
        mock_compute.assert_not_called()
