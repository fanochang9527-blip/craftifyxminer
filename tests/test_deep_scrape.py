"""Unit tests for pipeline.deep_scrape — media extraction and storage."""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.deep_scrape import _store_deep_scrape_results


def _make_tweet_item(tweet_id: str, username: str, media_list: list[dict]) -> dict:
    """Helper to construct an Apify tweet-scraper item."""
    return {
        "id": tweet_id,
        "author": {
            "userName": username,
            "followers": 1000,
            "following": 200,
            "statusesCount": 500,
        },
        "text": "Test tweet",
        "likeCount": 10,
        "retweetCount": 5,
        "replyCount": 2,
        "viewCount": 100,
        "createdAt": "2024-01-01T00:00:00Z",
        "extendedEntities": {"media": media_list},
    }


class TestStoreDeepScrapeResults:
    @patch("pipeline.deep_scrape.get_cursor")
    def test_extracts_photo_media_types(self, mock_get_cursor):
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda self: mock_cursor
        mock_cursor.__exit__ = lambda self, *args: False
        mock_get_cursor.return_value = mock_cursor

        # Simulate creator exists
        mock_cursor.fetchone.side_effect = [
            {"id": 1},  # UPDATE creators RETURNING id
            {"is_seed": False},  # SELECT is_seed
        ]

        items = [
            _make_tweet_item("tw1", "user1", [
                {"media_url_https": "https://pbs.twimg.com/media/photo1.jpg", "type": "photo"},
                {"media_url_https": "https://pbs.twimg.com/media/photo2.jpg", "type": "photo"},
            ]),
        ]

        _store_deep_scrape_results(items)

        # Find the INSERT INTO tweets call
        insert_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "INSERT INTO tweets" in str(call.args[0])
        ]
        assert len(insert_calls) == 1
        sql, params = insert_calls[0].args

        # params[8] = media_urls, params[9] = media_types
        media_urls = params[8]
        media_types = params[9]

        assert media_urls == ["https://pbs.twimg.com/media/photo1.jpg", "https://pbs.twimg.com/media/photo2.jpg"]
        assert media_types == ["photo", "photo"]

    @patch("pipeline.deep_scrape.get_cursor")
    def test_extracts_video_media_types(self, mock_get_cursor):
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda self: mock_cursor
        mock_cursor.__exit__ = lambda self, *args: False
        mock_get_cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {"id": 2},
            {"is_seed": False},
        ]

        items = [
            _make_tweet_item("tw2", "user2", [
                {"media_url_https": "https://pbs.twimg.com/media/video_poster.jpg", "type": "video"},
            ]),
        ]

        _store_deep_scrape_results(items)

        insert_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "INSERT INTO tweets" in str(call.args[0])
        ]
        assert len(insert_calls) == 1
        sql, params = insert_calls[0].args

        media_urls = params[8]
        media_types = params[9]

        assert media_urls == ["https://pbs.twimg.com/media/video_poster.jpg"]
        assert media_types == ["video"]

    @patch("pipeline.deep_scrape.get_cursor")
    def test_mixed_media_types(self, mock_get_cursor):
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda self: mock_cursor
        mock_cursor.__exit__ = lambda self, *args: False
        mock_get_cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {"id": 3},
            {"is_seed": False},
        ]

        items = [
            _make_tweet_item("tw3", "user3", [
                {"media_url_https": "https://pbs.twimg.com/media/photo.jpg", "type": "photo"},
                {"media_url_https": "https://pbs.twimg.com/media/gif.gif", "type": "animated_gif"},
                {"media_url_https": "https://pbs.twimg.com/media/video.jpg", "type": "video"},
            ]),
        ]

        _store_deep_scrape_results(items)

        insert_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "INSERT INTO tweets" in str(call.args[0])
        ]
        assert len(insert_calls) == 1
        sql, params = insert_calls[0].args

        media_urls = params[8]
        media_types = params[9]

        assert media_urls == [
            "https://pbs.twimg.com/media/photo.jpg",
            "https://pbs.twimg.com/media/gif.gif",
            "https://pbs.twimg.com/media/video.jpg",
        ]
        assert media_types == ["photo", "animated_gif", "video"]

    @patch("pipeline.deep_scrape.get_cursor")
    def test_no_media_stores_empty_arrays(self, mock_get_cursor):
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda self: mock_cursor
        mock_cursor.__exit__ = lambda self, *args: False
        mock_get_cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {"id": 4},
            {"is_seed": False},
        ]

        items = [
            _make_tweet_item("tw4", "user4", []),
        ]

        _store_deep_scrape_results(items)

        insert_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "INSERT INTO tweets" in str(call.args[0])
        ]
        assert len(insert_calls) == 1
        sql, params = insert_calls[0].args

        media_urls = params[8]
        media_types = params[9]

        assert media_urls == []
        assert media_types == []

    @patch("pipeline.deep_scrape.get_cursor")
    def test_fallback_media_url(self, mock_get_cursor):
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda self: mock_cursor
        mock_cursor.__exit__ = lambda self, *args: False
        mock_get_cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {"id": 5},
            {"is_seed": False},
        ]

        items = [
            _make_tweet_item("tw5", "user5", [
                {"media_url": "http://old.url/media.jpg", "type": "photo"},
            ]),
        ]

        _store_deep_scrape_results(items)

        insert_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "INSERT INTO tweets" in str(call.args[0])
        ]
        sql, params = insert_calls[0].args

        assert params[8] == ["http://old.url/media.jpg"]
        assert params[9] == ["photo"]
