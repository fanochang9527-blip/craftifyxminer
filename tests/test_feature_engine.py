"""Unit tests for pipeline.feature_engine — 10 维指标计算 (pure functions only)."""

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import pytest

from pipeline.feature_engine import (
    calc_audience,
    calc_character_consistency,
    calc_community,
    calc_data_confidence,
    calc_engagement,
    calc_monetization,
    calc_posting,
    calc_virality,
    circle_influence_score_from_seed_connections,
)


def _make_tweet(likes=0, retweets=0, replies=0, text="", created_at=None, media_urls=None):
    now = datetime.now(timezone.utc)
    return {
        "likes": likes,
        "retweets": retweets,
        "replies": replies,
        "text": text,
        "created_at": created_at or (now - timedelta(days=1)).isoformat(),
        "media_urls": media_urls or [],
    }


class TestAudience:
    def test_zero_followers(self):
        assert calc_audience(0) == 0.0

    def test_100_followers(self):
        score = calc_audience(100)
        assert 30 < score < 50

    def test_1m_followers_capped(self):
        assert calc_audience(1_000_000) == 100.0

    def test_10k_followers(self):
        score = calc_audience(10_000)
        assert 70 < score < 90

    def test_bot_penalty_high_ratio(self):
        normal = calc_audience(1000, following=500)
        penalized = calc_audience(1000, following=3000)
        assert penalized < normal

    def test_no_penalty_low_ratio(self):
        score_no_follow = calc_audience(1000, following=0)
        score_low_follow = calc_audience(1000, following=1000)
        assert score_no_follow == score_low_follow


class TestEngagement:
    def test_zero_followers(self):
        tweets = [_make_tweet(likes=100)]
        assert calc_engagement(tweets, 0) == 0.0

    def test_empty_tweets(self):
        assert calc_engagement([], 1000) == 0.0

    def test_normal_engagement(self):
        tweets = [_make_tweet(likes=10, retweets=5, replies=2)]
        score = calc_engagement(tweets, 1000)
        assert score > 0

    def test_high_engagement_capped(self):
        tweets = [_make_tweet(likes=5000, retweets=5000, replies=5000)]
        assert calc_engagement(tweets, 10) == 100.0

    def test_time_decay_single_tweet_same_engagement_equal(self):
        """One tweet: weighted avg equals raw engagement; weight factor cancels in numerator/denominator."""
        now = datetime.now(timezone.utc)
        recent = [_make_tweet(likes=100, created_at=(now - timedelta(days=1)).isoformat())]
        old = [_make_tweet(likes=100, created_at=(now - timedelta(days=20)).isoformat())]
        assert calc_engagement(recent, 1000) == calc_engagement(old, 1000)

    def test_time_decay_mixed_tweets_changes_score(self):
        """Multiple tweets: stale low-engagement tweets pull down the weighted average vs recent-only."""
        now = datetime.now(timezone.utc)
        mixed = [
            _make_tweet(likes=100, created_at=(now - timedelta(days=1)).isoformat()),
            _make_tweet(likes=10, created_at=(now - timedelta(days=20)).isoformat()),
        ]
        recent_only = [_make_tweet(likes=100, created_at=(now - timedelta(days=1)).isoformat())]
        assert calc_engagement(recent_only, 1000) > calc_engagement(mixed, 1000)


class TestVirality:
    def test_zero_monthly(self):
        assert calc_virality(100, 0) == 0.0

    def test_top3_equals_monthly(self):
        assert calc_virality(50, 50) == pytest.approx(10.0)

    def test_ratio_5x(self):
        assert calc_virality(500, 100) == pytest.approx(50.0)

    def test_capped_at_100(self):
        assert calc_virality(10000, 1) == 100.0


class TestPosting:
    def test_empty_tweets(self):
        assert calc_posting([]) == 0.0

    def test_tweets_without_dates_fallback(self):
        tweets = [_make_tweet() for _ in range(15)]
        for tw in tweets:
            tw["created_at"] = None
        score = calc_posting(tweets)
        assert score == pytest.approx(50.0)

    def test_daily_poster(self):
        now = datetime.now(timezone.utc)
        tweets = [
            _make_tweet(created_at=(now - timedelta(days=i)).isoformat())
            for i in range(30)
        ]
        score = calc_posting(tweets)
        assert score >= 95.0


class TestMonetization:
    def test_commerce_link(self):
        assert calc_monetization("Check my booth.pm/items/123", "") == 90.0

    def test_identity_keyword_high_conf(self):
        score = calc_monetization("Freelance illustrator | commission open", "")
        assert score >= 50.0

    def test_no_signals(self):
        assert calc_monetization("I love cats", "") == 0.0

    def test_website_field(self):
        assert calc_monetization("Artist", "https://etsy.com/shop/myshop") == 90.0


class TestCircleInfluence:
    def test_zero_connections(self):
        assert circle_influence_score_from_seed_connections(0) == 0.0

    def test_one_connection(self):
        assert circle_influence_score_from_seed_connections(1) == 20.0

    def test_five_connections_max(self):
        assert circle_influence_score_from_seed_connections(5) == 100.0

    def test_above_five_still_100(self):
        assert circle_influence_score_from_seed_connections(10) == 100.0

    def test_negative_clamped(self):
        assert circle_influence_score_from_seed_connections(-3) == 0.0


class TestCharacterConsistency:
    def test_no_tweets(self):
        assert calc_character_consistency([]) == 50.0

    def test_single_domain(self):
        tweets = [
            {"media_urls": ["https://pbs.twimg.com/media/a.jpg"]},
            {"media_urls": ["https://pbs.twimg.com/media/b.jpg"]},
        ]
        assert calc_character_consistency(tweets) == 100.0

    def test_mixed_domains(self):
        tweets = [
            {"media_urls": ["https://pbs.twimg.com/a.jpg"]},
            {"media_urls": ["https://other.com/b.jpg"]},
        ]
        score = calc_character_consistency(tweets)
        assert 40 < score < 60


class TestCommunity:
    def test_empty_tweets(self):
        assert calc_community([]) == 0.0

    def test_fanart_tweets_weighted(self):
        tweets = [_make_tweet(text="#fanart look!", retweets=10)]
        score = calc_community(tweets)
        assert score > 0

    def test_mention_tweets(self):
        tweets = [_make_tweet(text="Thanks @someone for the art!")]
        score = calc_community(tweets)
        assert score > 0

    def test_no_signals(self):
        tweets = [_make_tweet(text="Just a regular tweet")]
        score = calc_community(tweets)
        assert score >= 0


class TestDataConfidence:
    def test_new_empty_account(self):
        assert calc_data_confidence(0, 0) == 0.0

    def test_mature_complete(self):
        assert calc_data_confidence(2.0, 1.0) == 100.0

    def test_partial(self):
        score = calc_data_confidence(0.5, 0.5)
        assert 40 < score < 60
