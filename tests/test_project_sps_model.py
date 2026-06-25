"""Unit tests for pipeline.project_sps_model helpers."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.project_sps_model import (
    CREATOR_ENUM_FEATURES,
    CREATOR_FEATURES,
    PROJECT_ENUM_FEATURES,
    PROJECT_NUMERIC_FEATURES,
    SPS_MODEL_PROJECT_META_PATH,
    _build_feature_names,
    _build_feature_vector,
    sales_to_sps,
)


def _full_row(domain: str = "OC", product_attribute: str = "普货", price: float = 29.99) -> dict:
    row: dict = {
        "domain": domain,
        "product_attribute": product_attribute,
        "price": price,
        "creator_market_tier": "low",
    }
    for i, col in enumerate(CREATOR_FEATURES):
        row[col] = float(i)
    return row


class TestBuildFeatureVector:
    def test_length(self):
        v = _build_feature_vector(_full_row())
        expected_len = (
            len(PROJECT_ENUM_FEATURES)
            + len(PROJECT_NUMERIC_FEATURES)
            + len(CREATOR_ENUM_FEATURES)
            + len(CREATOR_FEATURES)
        )
        assert v.shape == (expected_len,)

    def test_domain_enum_encoding(self):
        v = _build_feature_vector(_full_row(domain="同人"))
        names = _build_feature_names()
        domain_idx = names.index("domain")
        assert v[domain_idx] == pytest.approx(1.0)

    def test_product_attribute_enum_encoding(self):
        v = _build_feature_vector(_full_row(product_attribute="带磁"))
        names = _build_feature_names()
        attr_idx = names.index("product_attribute")
        assert v[attr_idx] == pytest.approx(1.0)

    def test_numeric_price(self):
        v = _build_feature_vector(_full_row(price=19.99))
        names = _build_feature_names()
        price_idx = names.index("price")
        assert v[price_idx] == pytest.approx(19.99)

    def test_creator_features(self):
        v = _build_feature_vector(_full_row())
        names = _build_feature_names()
        for i, col in enumerate(CREATOR_FEATURES):
            idx = names.index(col)
            assert v[idx] == pytest.approx(float(i))

    def test_missing_creator_feature_defaults_to_zero(self):
        row = _full_row()
        del row["creator_followers_log"]
        v = _build_feature_vector(row)
        names = _build_feature_names()
        idx = names.index("creator_followers_log")
        assert v[idx] == 0.0

    def test_unknown_enum_value_encoded_as_negative_one(self):
        v = _build_feature_vector(_full_row(domain="未知领域"))
        names = _build_feature_names()
        domain_idx = names.index("domain")
        assert v[domain_idx] == pytest.approx(-1.0)


class TestSalesToSps:
    def _write_meta(self, tmp_path, normalizer: float = 100.0):
        import json

        fake_meta = tmp_path / "project_meta.json"
        fake_meta.write_text(json.dumps({"sps_project_sales_normalizer": normalizer}))
        return fake_meta

    def test_maps_to_1(self, tmp_path, monkeypatch):
        # 与现有 creator_scores.sps_score 口径一致：sales / normalizer
        fake_meta = self._write_meta(tmp_path, normalizer=100.0)
        monkeypatch.setattr(
            "pipeline.project_sps_model.SPS_MODEL_PROJECT_META_PATH", fake_meta
        )
        assert sales_to_sps(100.0) == 1.0

    def test_caps_at_100(self, tmp_path, monkeypatch):
        fake_meta = self._write_meta(tmp_path, normalizer=1.0)
        monkeypatch.setattr(
            "pipeline.project_sps_model.SPS_MODEL_PROJECT_META_PATH", fake_meta
        )
        assert sales_to_sps(500.0) == 100.0

    def test_zero(self, tmp_path, monkeypatch):
        fake_meta = self._write_meta(tmp_path, normalizer=100.0)
        monkeypatch.setattr(
            "pipeline.project_sps_model.SPS_MODEL_PROJECT_META_PATH", fake_meta
        )
        assert sales_to_sps(0.0) == 0.0
