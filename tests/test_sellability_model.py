"""Unit tests for pipeline.sellability_model."""

import sys
from unittest.mock import MagicMock, patch

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import numpy as np

from pipeline.sellability_model import (
    CONTINUOUS_FEATURE_COLS,
    FEATURE_COLS,
    FEATURE_COLS_V2,
    _build_feature_vector,
    _build_feature_vector_v2,
    _fit_scaler,
    _load_training_rows,
    _scale_features,
    predict_sellability,
    train_model,
)


class TestLoadTrainingRows:
    @patch("pipeline.growth_monitor.is_growth_system_mature", return_value=False)
    def test_raises_when_no_data(self, _mock_mature):
        with patch("pipeline.sellability_model.fetch_all", return_value=[]):
            try:
                _load_training_rows()
                assert False, "expected ValueError"
            except ValueError as e:
                assert "No training data" in str(e)

    @patch("pipeline.growth_monitor.is_growth_system_mature", return_value=False)
    def test_uses_reviewed_rows_first(self, _mock_mature):
        reviewed = [{"y": 1, "audience_score": 1.0, "creator_type": "unknown", "creator_id": 1}]
        with patch("pipeline.sellability_model.fetch_all", side_effect=[reviewed, [], []]):
            rows, weights = _load_training_rows()
            assert len(rows) == 1
            assert weights == [1.0]

    @patch("pipeline.growth_monitor.is_growth_system_mature", return_value=False)
    def test_seed_sales_threshold_labels(self, _mock_mature):
        reviewed = []
        seed_rows = [
            {"creator_id": 11, "y": 1, "creator_type": "unknown"},
            {"creator_id": 12, "y": 0, "creator_type": "unknown"},
            {"creator_id": 13, "y": None, "creator_type": "unknown"},
        ]
        with patch("pipeline.sellability_model.fetch_all", side_effect=[reviewed, seed_rows, []]):
            rows, weights = _load_training_rows()
            ys = sorted(int(r["y"]) for r in rows)
            assert ys == [0, 1]
            assert weights == [1.0, 1.0]


class TestPredictSellability:
    def test_no_model_returns_none(self, tmp_path):
        fake = tmp_path / "missing.joblib"
        with patch("pipeline.sellability_model.SELLABILITY_MODEL_PATH", fake):
            row = {"audience_score": 1, "creator_type": "unknown"}
            assert predict_sellability(row) is None


class _AlwaysPositiveModel:
    classes_ = np.array([1])

    def predict_proba(self, X):
        return np.ones((X.shape[0], 1))


class TestSingleClassSupport:
    @patch(
        "pipeline.sellability_model.load_model",
        return_value={"model": _AlwaysPositiveModel(), "scaler": None},
    )
    def test_single_class_model_predicts_100(self, _mock):
        row = {
            "audience_score": 1,
            "has_monetization_signal": True,
            "social_engagement_rate": 0.01,
            "conversation_rate": 0.01,
            "fanart_ratio": 0.01,
            "mention_rate": 0.01,
            "retweet_rate": 1,
            "audience_is_nsfw": False,
            "audience_is_multi_platform": False,
            "creator_type": "unknown",
        }
        assert predict_sellability(row) == 100.0


class TestScaler:
    def test_scaler_only_affects_continuous_features(self):
        # 构造 2 个样本： audience_score=0/100, 其余信号固定为 1
        rows = [
            {
                "audience_score": 0.0,
                "has_monetization_signal": True,
                "social_engagement_rate": 0.01,
                "conversation_rate": 0.01,
                "fanart_ratio": 0.01,
                "mention_rate": 0.01,
                "retweet_rate": 1.0,
                "audience_is_nsfw": True,
                "audience_is_multi_platform": False,
                "creator_type": "oc_creator",
            },
            {
                "audience_score": 100.0,
                "has_monetization_signal": False,
                "social_engagement_rate": 0.01,
                "conversation_rate": 0.01,
                "fanart_ratio": 0.01,
                "mention_rate": 0.01,
                "retweet_rate": 1.0,
                "audience_is_nsfw": False,
                "audience_is_multi_platform": True,
                "creator_type": "fan_artist",
            },
        ]
        X = np.array([_build_feature_vector(r) for r in rows])
        scaler = _fit_scaler(X)
        X_scaled = _scale_features(X, scaler)

        # 连续特征的 mean 应为 0（标准化后）
        for col in CONTINUOUS_FEATURE_COLS:
            idx = FEATURE_COLS.index(col)
            assert abs(X_scaled[:, idx].mean()) < 1e-6

        # 布尔/ordinal 特征保持原值
        assert X_scaled[:, FEATURE_COLS.index("has_monetization_signal")].tolist() == [1.0, 0.0]
        assert X_scaled[:, FEATURE_COLS.index("audience_is_nsfw")].tolist() == [1.0, 0.0]
        assert X_scaled[:, FEATURE_COLS.index("audience_is_multi_platform")].tolist() == [0.0, 1.0]
        assert X_scaled[:, FEATURE_COLS.index("creator_type")].tolist() == [0.0, 2.0]


class TestBuildFeatureVector:
    def test_length_10(self):
        row = {k: float(i) for i, k in enumerate(FEATURE_COLS)}
        row["creator_type"] = "unknown"
        v = _build_feature_vector(row)
        assert v.shape == (10,)

    def test_engagement_score_replaced_by_raw_rates(self):
        assert "engagement_score" not in FEATURE_COLS
        assert "social_engagement_rate" in FEATURE_COLS
        assert "conversation_rate" in FEATURE_COLS

    def test_audience_segment_score_replaced_by_booleans(self):
        assert "audience_segment_score" not in FEATURE_COLS
        assert "audience_is_nsfw" in FEATURE_COLS
        assert "audience_is_multi_platform" in FEATURE_COLS

    def test_monetization_score_replaced_by_signal(self):
        assert "monetization_score" not in FEATURE_COLS
        assert "has_monetization_signal" in FEATURE_COLS

    def test_community_score_replaced_by_raw_signals(self):
        assert "community_score" not in FEATURE_COLS
        assert "fanart_ratio" in FEATURE_COLS
        assert "mention_rate" in FEATURE_COLS
        assert "retweet_rate" in FEATURE_COLS

    def test_boolean_flags_encoded_as_float(self):
        row = {k: 0.0 for k in FEATURE_COLS}
        row["audience_is_nsfw"] = True
        row["audience_is_multi_platform"] = False
        row["has_monetization_signal"] = True
        row["creator_type"] = "unknown"
        v = _build_feature_vector(row)
        assert v[FEATURE_COLS.index("audience_is_nsfw")] == 1.0
        assert v[FEATURE_COLS.index("audience_is_multi_platform")] == 0.0
        assert v[FEATURE_COLS.index("has_monetization_signal")] == 1.0

    def test_creator_type_ordinal(self):
        row = {k: 0.0 for k in FEATURE_COLS}
        row["creator_type"] = "fan_artist"
        v = _build_feature_vector(row)
        from config.settings import CREATOR_TYPES
        assert v[-1] == float(CREATOR_TYPES.index("fan_artist"))

    def test_unknown_creator_type_fallback(self):
        row = {k: 0.0 for k in FEATURE_COLS}
        row["creator_type"] = "not_a_real_type"
        v = _build_feature_vector(row)
        from config.settings import CREATOR_TYPES
        assert v[-1] == float(CREATOR_TYPES.index("unknown"))


class TestBuildFeatureVectorV2:
    def test_length_10(self):
        row = {k: float(i) for i, k in enumerate(FEATURE_COLS_V2)}
        row["creator_type"] = "unknown"
        v = _build_feature_vector_v2(row)
        assert v.shape == (10,)

    def test_audience_segment_score_replaced_by_booleans(self):
        assert "audience_segment_score" not in FEATURE_COLS_V2
        assert "audience_is_nsfw" in FEATURE_COLS_V2
        assert "audience_is_multi_platform" in FEATURE_COLS_V2

    def test_monetization_score_replaced_by_signal(self):
        assert "monetization_score" not in FEATURE_COLS_V2
        assert "has_monetization_signal" in FEATURE_COLS_V2

    def test_community_score_replaced_by_raw_signals(self):
        assert "community_score" not in FEATURE_COLS_V2
        assert "fanart_ratio" in FEATURE_COLS_V2
        assert "mention_rate" in FEATURE_COLS_V2
        assert "retweet_rate" in FEATURE_COLS_V2

    def test_creator_type_ordinal(self):
        row = {k: 0.0 for k in FEATURE_COLS_V2}
        row["creator_type"] = "oc_creator"
        v = _build_feature_vector_v2(row)
        from config.settings import CREATOR_TYPES
        assert v[-1] == float(CREATOR_TYPES.index("oc_creator"))
