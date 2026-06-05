"""Unit tests for pipeline.sellability_model."""

import sys
from unittest.mock import MagicMock, patch

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import numpy as np

from pipeline.sellability_model import (
    FEATURE_COLS_V2,
    _build_feature_vector_v2,
    _load_training_rows,
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
    @patch("pipeline.sellability_model.load_model", return_value=_AlwaysPositiveModel())
    def test_single_class_model_predicts_100(self, _mock):
        row = {
            "audience_score": 1,
            "engagement_score": 1,
            "virality_score": 1,
            "posting_score": 1,
            "monetization_score": 1,
            "growth_score": 1,
            "character_consistency": 1,
            "community_score": 1,
            "creator_type": "unknown",
        }
        assert predict_sellability(row) == 100.0


class TestBuildFeatureVectorV2:
    def test_length_13(self):
        row = {k: float(i) for i, k in enumerate(FEATURE_COLS_V2)}
        row["creator_type"] = "unknown"
        v = _build_feature_vector_v2(row)
        assert v.shape == (13,)

    def test_one_hot_oc_creator(self):
        row = {k: 0.0 for k in FEATURE_COLS_V2}
        row["creator_type"] = "oc_creator"
        v = _build_feature_vector_v2(row)
        tail = v[7:].tolist()
        from config.settings import CREATOR_TYPES
        expected = [1.0 if t == "oc_creator" else 0.0 for t in CREATOR_TYPES]
        assert tail == expected
