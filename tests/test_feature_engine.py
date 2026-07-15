"""Unit tests for pipeline.feature_engine — 9 维指标计算 (pure functions only)."""

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import pytest

from pipeline.feature_engine import (
    calc_audience,
    calc_audience_segment,
    calc_audience_segment_booleans,
    calc_character_consistency,
    calc_community,
    calc_conversation_rate,
    calc_days_since_last_post,
    calc_engagement,
    calc_fanart_ratio,
    calc_mention_rate,
    calc_monetization,
    calc_monetization_signal,
    calc_monthly_engagement_base,
    calc_posting,
    calc_retweet_rate,
    calc_social_engagement_rate,
    calc_virality,
    calc_virality_raw,
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


class TestDaysSinceLastPost:
    def test_empty_tweets(self):
        assert calc_days_since_last_post([]) == 365.0

    def test_no_valid_dates(self):
        tweets = [_make_tweet(), _make_tweet()]
        for tw in tweets:
            tw["created_at"] = None
        assert calc_days_since_last_post(tweets) == 365.0

    def test_recent_post(self):
        now = datetime.now(timezone.utc)
        tweets = [_make_tweet(created_at=(now - timedelta(hours=12)).isoformat())]
        days = calc_days_since_last_post(tweets)
        assert 0.0 <= days <= 1.0

    def test_stale_post(self):
        now = datetime.now(timezone.utc)
        tweets = [_make_tweet(created_at=(now - timedelta(days=60)).isoformat())]
        days = calc_days_since_last_post(tweets)
        assert 59.0 <= days <= 61.0

    def test_uses_latest_date(self):
        now = datetime.now(timezone.utc)
        tweets = [
            _make_tweet(created_at=(now - timedelta(days=30)).isoformat()),
            _make_tweet(created_at=(now - timedelta(days=5)).isoformat()),
            _make_tweet(created_at=(now - timedelta(days=10)).isoformat()),
        ]
        days = calc_days_since_last_post(tweets)
        assert 4.0 <= days <= 6.0


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


class TestAudienceSegment:
    def test_nsfw_in_bio(self):
        score, seg = calc_audience_segment("NSFW artist", "", "user1")
        assert seg == "nsfw"
        assert score == 20.0

    def test_nsfw_in_username(self):
        score, seg = calc_audience_segment("Just an artist", "", "nsfw_creator")
        assert seg == "nsfw"
        assert score == 20.0

    def test_emoji_in_bio(self):
        score, seg = calc_audience_segment("Adult content 🔞", "", "user2")
        assert seg == "nsfw"
        assert score == 20.0

    def test_emoji_in_username(self):
        score, seg = calc_audience_segment("Bio here", "", "artist🔞")
        assert seg == "nsfw"
        assert score == 20.0

    def test_multi_platform_instagram(self):
        score, seg = calc_audience_segment("Find me on instagram.com/art", "", "user3")
        assert seg == "multi_platform"
        assert score == 80.0

    def test_multi_platform_website(self):
        score, seg = calc_audience_segment("Artist", "https://linktr.ee/artist", "user4")
        assert seg == "multi_platform"
        assert score == 80.0

    def test_monetization_domain_is_mainstream_segment(self):
        # booth.pm 属于店铺平台，不再是 multi_platform；受众分段回到 mainstream
        score, seg = calc_audience_segment("Artist", "https://booth.pm/123", "user4")
        assert seg == "mainstream"
        assert score == 50.0

    def test_mainstream_no_signals(self):
        score, seg = calc_audience_segment("Just a normal bio", "", "user5")
        assert seg == "mainstream"
        assert score == 50.0

    def test_nsfw_priority_over_multi_platform(self):
        """NSFW 优先级应高于多平台判定。"""
        score, seg = calc_audience_segment("NSFW 🔞 instagram.com/art", "", "user6")
        assert seg == "nsfw"
        assert score == 20.0

    def test_empty_bio_and_username(self):
        score, seg = calc_audience_segment("", "", "")
        assert seg == "mainstream"
        assert score == 50.0


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


class TestSocialEngagementRate:
    def test_zero_followers(self):
        tweets = [_make_tweet(likes=10, retweets=5)]
        assert calc_social_engagement_rate(tweets, 0) == 0.0

    def test_empty_tweets(self):
        assert calc_social_engagement_rate([], 1000) == 0.0

    def test_normal_rate(self):
        tweets = [_make_tweet(likes=10, retweets=5) for _ in range(2)]
        rate = calc_social_engagement_rate(tweets, 1000)
        # avg_likes=10, avg_rts=5, raw rate = 15/1000 = 0.015
        assert rate == pytest.approx(0.015)


class TestConversationRate:
    def test_zero_followers(self):
        tweets = [_make_tweet(replies=3)]
        assert calc_conversation_rate(tweets, 0) == 0.0

    def test_normal_rate(self):
        tweets = [_make_tweet(replies=10) for _ in range(2)]
        rate = calc_conversation_rate(tweets, 1000)
        # avg_replies=10, raw rate = 10/1000 = 0.01
        assert rate == pytest.approx(0.01)


class TestFanartRatio:
    def test_empty_tweets(self):
        assert calc_fanart_ratio([]) == 0.0

    def test_all_fanart(self):
        tweets = [_make_tweet(text="#fanart art1"), _make_tweet(text="fanart art2")]
        assert calc_fanart_ratio(tweets) == 1.0

    def test_half_fanart(self):
        tweets = [_make_tweet(text="#fanart art1"), _make_tweet(text="normal tweet")]
        assert calc_fanart_ratio(tweets) == 0.5


class TestMentionRate:
    def test_empty_tweets(self):
        assert calc_mention_rate([]) == 0.0

    def test_half_mentions(self):
        tweets = [_make_tweet(text="hello @user"), _make_tweet(text="no mention")]
        assert calc_mention_rate(tweets) == 0.5

    def test_no_mentions(self):
        tweets = [_make_tweet(text="no mention"), _make_tweet(text="also none")]
        assert calc_mention_rate(tweets) == 0.0


class TestRetweetRate:
    def test_empty_tweets(self):
        assert calc_retweet_rate([]) == 0.0

    def test_average(self):
        tweets = [_make_tweet(retweets=10), _make_tweet(retweets=20)]
        assert calc_retweet_rate(tweets) == 15.0


class TestViralityRaw:
    def test_zero_monthly(self):
        assert calc_virality_raw(100, 0) == 0.0

    def test_not_capped(self):
        # 原公式 capped 在 10，新公式不封顶
        assert calc_virality_raw(1000, 10) == 100.0

    def test_ratio_5x(self):
        assert calc_virality_raw(500, 100) == 5.0


class TestMonthlyEngagementBase:
    def test_returns_monthly_avg(self):
        assert calc_monthly_engagement_base(42.0) == 42.0


class TestAudienceSegmentBooleans:
    def test_nsfw_detection(self):
        score, segment = calc_audience_segment("NSFW artist 🔞", "", "user")
        is_nsfw, _ = calc_audience_segment_booleans("NSFW artist 🔞", "", "user")
        assert segment == "nsfw"
        assert is_nsfw is True

    def test_multi_platform_and_monetization_are_separated(self):
        # 只有 shop 链接：monetization=True, multi_platform=False
        bio_shop = "commissions open https://ko-fi.com/artist"
        is_nsfw, is_multi = calc_audience_segment_booleans(bio_shop, "", "user")
        has_monetization = calc_monetization_signal(bio_shop, "")
        assert is_multi is False
        assert has_monetization is True

        # 只有社交聚合链接：monetization=False, multi_platform=True
        bio_social = "find me on https://linktr.ee/artist"
        is_nsfw2, is_multi2 = calc_audience_segment_booleans(bio_social, "", "user")
        has_monetization2 = calc_monetization_signal(bio_social, "")
        assert is_multi2 is True
        assert has_monetization2 is False

    def test_multi_platform_detects_unknown_external_url(self):
        # 未知但非 X/非店铺/非邮箱的外部链接也应被识别
        bio = "portfolio: https://artist.portfolio.site"
        _, is_multi = calc_audience_segment_booleans(bio, "", "user")
        assert is_multi is True

    def test_x_and_email_do_not_count_as_multi_platform(self):
        bio = "contact me at artist@gmail.com or x.com/artist"
        _, is_multi = calc_audience_segment_booleans(bio, "", "user")
        assert is_multi is False

