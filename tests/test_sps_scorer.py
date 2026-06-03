"""Unit tests for pipeline.sps_scorer — SPS 评分 + 中心度 (pure functions only)."""

import sys
from unittest.mock import MagicMock, patch

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import pytest

from pipeline.sps_scorer import (
    FEATURE_KEYS,
    WEIGHT_KEYS,
    calc_contact_probability,
    calc_sps,
    classify_centrality,
    get_weights_for_type,
)


class TestClassifyCentrality:
    def test_hub(self):
        assert classify_centrality(5) == "Hub"
        assert classify_centrality(10) == "Hub"

    def test_connector(self):
        assert classify_centrality(2) == "Connector"
        assert classify_centrality(4) == "Connector"

    def test_peripheral(self):
        assert classify_centrality(0) == "Peripheral"
        assert classify_centrality(1) == "Peripheral"


class TestGetWeights:
    def test_known_type(self):
        w = get_weights_for_type("oc_creator")
        assert "audience" in w
        assert "character_consistency" in w
        assert abs(sum(w.values()) - 1.0) < 0.01

    def test_unknown_falls_back(self):
        w = get_weights_for_type("totally_unknown_type")
        assert isinstance(w, dict)
        assert len(w) >= 9

    def test_all_types_sum_to_one(self):
        for ctype in ["oc_creator", "vtuber", "fan_artist", "game_creator", "content_creator"]:
            w = get_weights_for_type(ctype)
            assert abs(sum(w.values()) - 1.0) < 0.01, f"{ctype} weights don't sum to 1.0"


class TestCalcSPS:
    @patch("pipeline.sps_model.predict_sps", return_value=None)
    def test_all_zero(self, _mock_predict):
        features = {fk: 0.0 for fk in FEATURE_KEYS}
        assert calc_sps(features, "content_creator") == 0.0

    @patch("pipeline.sps_model.predict_sps", return_value=None)
    def test_all_100(self, _mock_predict):
        features = {fk: 100.0 for fk in FEATURE_KEYS}
        sps = calc_sps(features, "content_creator")
        assert sps == pytest.approx(100.0, abs=1)

    @patch("pipeline.sps_model.predict_sps", return_value=None)
    def test_partial_scores(self, _mock_predict):
        features = {fk: 50.0 for fk in FEATURE_KEYS}
        sps = calc_sps(features, "oc_creator")
        assert sps == pytest.approx(50.0, abs=1)

    @patch("pipeline.sps_model.predict_sps", return_value=None)
    def test_weights_applied(self, _mock_predict):
        features = {fk: 0.0 for fk in FEATURE_KEYS}
        features["monetization_score"] = 100.0
        sps_oc = calc_sps(features, "oc_creator")
        sps_vt = calc_sps(features, "vtuber")
        # oc_creator monetization weight 0.25 vs vtuber 0.15
        assert sps_oc > sps_vt


class TestContactProbability:
    def test_zero(self):
        assert calc_contact_probability(0, 0) == 0.0

    def test_high_sps(self):
        prob = calc_contact_probability(80, 90)
        assert 0.5 < prob <= 1.0

    def test_capped_at_one(self):
        prob = calc_contact_probability(100, 100)
        assert prob <= 1.0


class TestKeyAlignment:
    def test_same_length(self):
        assert len(FEATURE_KEYS) == len(WEIGHT_KEYS) == 9


# ---------------------------------------------------------------------------
# Tests — score_creator skips alerted creators
# ---------------------------------------------------------------------------

class TestScoreCreatorAlertSkip:
    @patch("pipeline.sps_scorer.fetch_one")
    def test_skips_alerted_creator(self, mock_fetch_one):
        from pipeline.sps_scorer import score_creator

        # first call: alerted_at check
        mock_fetch_one.return_value = {"alerted_at": "2024-01-01T00:00:00"}
        result = score_creator(1)
        assert result is None

    @patch("pipeline.sps_scorer.fetch_one")
    def test_scores_non_alerted_creator(self, mock_fetch_one):
        from pipeline.sps_scorer import score_creator
        from unittest.mock import patch

        # first call: follower_alert_at check → None
        # subsequent calls: features, type, seed_connections
        mock_fetch_one.side_effect = [
            {"follower_alert_at": None},
            {
                "audience_score": 50.0,
                "engagement_score": 50.0,
                "virality_score": 50.0,
                "posting_score": 50.0,
                "monetization_score": 50.0,
                "growth_score": 50.0,
                "character_consistency": 50.0,
                "community_score": 50.0,
                "audience_segment_score": 50.0,
            },
            {"creator_type": "content_creator"},
            {"cnt": 0},
        ]
        with patch("pipeline.sps_scorer.get_cursor") as mock_get_cursor:
            mock_cursor = MagicMock()
            mock_get_cursor.return_value.__enter__ = lambda self: mock_cursor
            mock_get_cursor.return_value.__exit__ = lambda self, *args: False
            result = score_creator(1)
            assert result is not None
            assert result["creator_id"] == 1
