"""Unit tests for pipeline.creator_dna — pure helpers (no API calls)."""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.creator_dna import (
    _compute_raw_features,
    _determine_market_tier,
    _extract_multi_platform,
    _extract_nsfw,
    _extract_shop_signals,
    _normalize_llm_result,
)


class TestDetermineMarketTier:
    def test_high_tier_by_country(self):
        assert _determine_market_tier("United States", None, None) == "high"

    def test_high_tier_by_location(self):
        assert _determine_market_tier(None, None, "Tokyo, Japan") == "high"

    def test_mid_tier_by_country(self):
        assert _determine_market_tier("Brazil", None, None) == "mid"

    def test_low_tier_by_country(self):
        assert _determine_market_tier("India", None, None) == "low"

    def test_default_low_when_empty(self):
        assert _determine_market_tier(None, None, None) == "low"


class TestExtractShopSignals:
    def test_detects_booth_link(self):
        bio = "Check my shop: https://example.booth.pm"
        has_shop, platforms = _extract_shop_signals(bio, None, [])
        assert has_shop is True
        assert "booth" in platforms

    def test_detects_patreon_in_text(self):
        bio = "Support me on patreon"
        has_shop, platforms = _extract_shop_signals(bio, None, [])
        assert has_shop is True
        assert "patreon" in platforms

    def test_no_shop(self):
        bio = "Just an artist posting art"
        has_shop, platforms = _extract_shop_signals(bio, None, [])
        assert has_shop is False
        assert platforms == []


class TestExtractMultiPlatform:
    def test_detects_pixiv(self):
        bio = "Artstation: artstation.com/artist pixiv.net/users/123"
        assert _extract_multi_platform(bio, None) is True

    def test_no_other_platform(self):
        bio = "Just posting on X"
        assert _extract_multi_platform(bio, None) is False


class TestExtractNsfw:
    def test_detects_nsfw_keyword(self):
        assert _extract_nsfw("NSFW artist", "user", []) is True

    def test_detects_emoji(self):
        assert _extract_nsfw("Adult content 🔞", "user", []) is True

    def test_detects_in_tweets(self):
        tweets = [{"text": "Some lewd art here"}]
        assert _extract_nsfw("artist", "user", tweets) is True

    def test_clean(self):
        assert _extract_nsfw("Family friendly art", "user", []) is False


class TestComputeRawFeatures:
    def test_basic_computation(self):
        creator = {
            "followers": 1000,
            "following": 200,
            "account_age_days": 365,
        }
        now = __import__("datetime", fromlist=["datetime"]).datetime.utcnow()
        tweets = [
            {"likes": 10, "retweets": 2, "replies": 1, "created_at": now},
            {"likes": 20, "retweets": 4, "replies": 3, "created_at": now},
        ]
        feats = _compute_raw_features(creator, tweets)
        assert "followers_log" in feats
        assert "following_follower_ratio" in feats
        assert "avg_daily_posts_30d" in feats
        assert "reply_engagement_rate" in feats
        assert "account_age_days_log" in feats
        assert feats["followers_log"] == pytest.approx(6.908, rel=1e-3)
        assert feats["following_follower_ratio"] == pytest.approx(0.2)


class TestNormalizeLLMResult:
    def test_valid_content_classifications(self):
        result = {
            "character_tags": {
                "content_classifications": ["furry", "anime"],
                "tags": ["cat", "animal_ears"],
                "style_tags": ["chibi"],
                "theme_tags": ["cute"],
            },
        }
        normalized = _normalize_llm_result(result)
        assert normalized["content_classifications"] == ["furry", "anime"]
        assert "cat" in normalized["tags"]
        assert "chibi" in normalized["style_tags"]
        assert "cute" in normalized["theme_tags"]

    def test_invalid_content_defaults_anime(self):
        result = {
            "character_tags": {
                "content_classifications": ["invalid_tag"],
            },
        }
        normalized = _normalize_llm_result(result)
        assert normalized["content_classifications"] == ["anime"]

    def test_content_max_three(self):
        result = {
            "character_tags": {
                "content_classifications": ["furry", "anime", "gaming", "nsfw"],
            },
        }
        normalized = _normalize_llm_result(result)
        assert len(normalized["content_classifications"]) == 3
        assert "nsfw" not in normalized["content_classifications"]
