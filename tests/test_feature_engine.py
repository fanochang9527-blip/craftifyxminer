"""Unit tests for pipeline.feature_engine — 10 维指标计算 (pure functions only)."""

import sys
from types import ModuleType
from unittest.mock import MagicMock

# Stub heavy dependencies so tests run without psycopg2 / a real DB
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


class TestAudience:
    def test_zero_followers(self):
        assert calc_audience(0) == pytest.approx(0.0, abs=1)

    def test_100_followers(self):
        score = calc_audience(100)
        assert 30 < score < 50

    def test_1m_followers_capped(self):
        assert calc_audience(1_000_000) == 100.0

    def test_10k_followers(self):
        score = calc_audience(10_000)
        assert 70 < score < 90


class TestEngagement:
    def test_zero_followers(self):
        assert calc_engagement(100, 50, 10, 0) == 0.0

    def test_normal(self):
        # (10 + 5*2 + 2*3) / 1000 * 100 = 2.6
        score = calc_engagement(10, 5, 2, 1000)
        assert 2 < score < 5

    def test_capped_at_100(self):
        assert calc_engagement(5000, 5000, 5000, 10) == 100.0


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
    def test_zero_posts(self):
        assert calc_posting(0) == 0.0

    def test_daily_poster(self):
        assert calc_posting(30) == 100.0

    def test_15_posts(self):
        assert calc_posting(15) == pytest.approx(50.0)

    def test_capped(self):
        assert calc_posting(100) == 100.0


class TestMonetization:
    def test_commerce_link(self):
        assert calc_monetization("Check my booth.pm/items/123", "") == 90.0

    def test_action_keyword(self):
        assert calc_monetization("commission open | DM me", "") == 60.0

    def test_weak_signal(self):
        assert calc_monetization("Visit my shop", "") == 30.0

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
    def test_zero(self):
        assert calc_community(0, 0) == 0.0

    def test_normal(self):
        # (5*2 + 2*5) / 100 * 100 = 20
        assert calc_community(5, 2) == pytest.approx(20.0)

    def test_capped(self):
        assert calc_community(500, 500) == 100.0


class TestDataConfidence:
    def test_new_empty_account(self):
        assert calc_data_confidence(0, 0) == 0.0

    def test_mature_complete(self):
        assert calc_data_confidence(2.0, 1.0) == 100.0

    def test_partial(self):
        score = calc_data_confidence(0.5, 0.5)
        assert 40 < score < 60
