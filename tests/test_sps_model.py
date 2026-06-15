"""Unit tests for pipeline.sps_model — pure helpers (no trained model file required)."""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from config.settings import CREATOR_TYPES
from pipeline.sps_model import (
    FEATURE_COLS,
    FEATURE_COLS_V2,
    _build_feature_vector,
    _build_feature_vector_v2,
    predict_sps,
)


class TestBuildFeatureVector:
    def test_length_12(self):
        row = {k: float(i) for i, k in enumerate(FEATURE_COLS)}
        row["creator_type"] = "unknown"
        v = _build_feature_vector(row)
        assert v.shape == (12,)

    def test_one_hot_oc_creator(self):
        row = {k: 0.0 for k in FEATURE_COLS}
        row["creator_type"] = "oc_creator"
        v = _build_feature_vector(row)
        tail = v[6:].tolist()
        expected = [1.0 if t == "oc_creator" else 0.0 for t in CREATOR_TYPES]
        assert tail == expected

    def test_one_hot_unknown(self):
        row = {k: 1.0 for k in FEATURE_COLS}
        row["creator_type"] = "unknown"
        v = _build_feature_vector(row)
        idx = CREATOR_TYPES.index("unknown")
        assert v[6 + idx] == 1.0
        assert sum(v[6:]) == pytest.approx(1.0)

    def test_missing_creator_type_defaults_unknown_one_hot(self):
        row = {k: 5.0 for k in FEATURE_COLS}
        v = _build_feature_vector(row)
        idx = CREATOR_TYPES.index("unknown")
        assert v[6 + idx] == 1.0


class TestPredictSPS:
    def test_no_model_file_returns_none(self, tmp_path):
        fake = tmp_path / "missing.joblib"
        with patch("pipeline.sps_model.MODEL_PATH", fake):
            from pipeline.sps_model import predict_sps as predict_fn

            row = {k: 50.0 for k in FEATURE_COLS}
            row["creator_type"] = "vtuber"
            assert predict_fn(row) is None


class TestBuildFeatureVectorV2:
    def test_length_14(self):
        row = {k: float(i) for i, k in enumerate(FEATURE_COLS_V2)}
        row["creator_type"] = "unknown"
        v = _build_feature_vector_v2(row)
        assert v.shape == (14,)

    def test_one_hot_vtuber(self):
        row = {k: 0.0 for k in FEATURE_COLS_V2}
        row["creator_type"] = "vtuber"
        v = _build_feature_vector_v2(row)
        from config.settings import CREATOR_TYPES
        idx = 8 + CREATOR_TYPES.index("vtuber")
        assert v[idx] == 1.0
