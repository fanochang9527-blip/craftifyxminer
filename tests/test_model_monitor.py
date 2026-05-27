"""Unit tests for pipeline.model_monitor — dual-model evaluation."""

import sys
from unittest.mock import MagicMock, mock_open, patch

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import numpy as np
import pytest

from pipeline.model_monitor import (
    evaluate_model,
    evaluate_sellability,
    evaluate_sps,
)


class TestEvaluateSellability:
    @patch("pipeline.model_monitor.fetch_all")
    @patch("pipeline.model_monitor._store_evaluation")
    @patch("pipeline.model_monitor._check_sellability_alerts")
    @patch(
        "builtins.open",
        mock_open(read_data='{"model_type":"XGBClassifier","n_samples":42,"trained_at":"2026-01-01T00:00:00"}'),
    )
    def test_basic(self, mock_alerts, mock_store, mock_fetch):
        mock_fetch.return_value = [
            {"sellability_score": 80.0, "bd_decision": "interested"},
            {"sellability_score": 70.0, "bd_decision": "interested"},
            {"sellability_score": 30.0, "bd_decision": "rejected_unfit"},
            {"sellability_score": 20.0, "bd_decision": "rejected_not_creator"},
        ]
        result = evaluate_sellability()
        assert result is not None
        assert result["model_name"] == "sellability"
        assert result["n_seeds"] == 42
        assert result["recall"] == 1.0
        assert result["precision_score"] == 1.0
        assert result["precision_at_250"] is None
        assert result["spearman_corr"] is None
        mock_store.assert_called_once()

    @patch("pipeline.model_monitor.fetch_all")
    def test_insufficient_data(self, mock_fetch):
        mock_fetch.return_value = []
        result = evaluate_sellability()
        assert result is None


class TestEvaluateSps:
    @patch("pipeline.model_monitor.fetch_all")
    @patch("pipeline.model_monitor._store_evaluation")
    @patch("pipeline.model_monitor._check_sps_alerts")
    @patch(
        "builtins.open",
        mock_open(read_data='{"model_type":"XGBoost","n_samples":36,"trained_at":"2026-01-01T00:00:00"}'),
    )
    def test_with_sales_feedback(self, mock_alerts, mock_store, mock_fetch):
        def _fake_fetch(sql):
            if "sales_feedback" in sql:
                return [
                    {"predicted_sales": 100.0, "actual_sales": 110.0},
                    {"predicted_sales": 200.0, "actual_sales": 190.0},
                    {"predicted_sales": 300.0, "actual_sales": 310.0},
                    {"predicted_sales": 50.0, "actual_sales": 60.0},
                    {"predicted_sales": 150.0, "actual_sales": 140.0},
                ]
            return [
                {"sps_score": 90.0, "bd_decision": "interested"},
                {"sps_score": 80.0, "bd_decision": "interested"},
                {"sps_score": 40.0, "bd_decision": "rejected_unfit"},
                {"sps_score": 30.0, "bd_decision": "rejected_not_creator"},
            ]

        mock_fetch.side_effect = _fake_fetch
        result = evaluate_sps()
        assert result is not None
        assert result["model_name"] == "sps"
        assert result["n_seeds"] == 36
        assert result["recall"] is None
        assert result["precision_at_250"] is not None
        assert result["spearman_corr"] is not None
        assert result["r2"] is not None
        assert result["mae"] is not None
        mock_store.assert_called_once()

    @patch("pipeline.model_monitor.fetch_all")
    @patch("pipeline.model_monitor._store_evaluation")
    @patch("pipeline.model_monitor._check_sps_alerts")
    @patch(
        "builtins.open",
        mock_open(read_data='{"model_type":"Ridge","n_samples":25,"trained_at":"2026-01-01T00:00:00"}'),
    )
    def test_without_sales_feedback(self, mock_alerts, mock_store, mock_fetch):
        def _fake_fetch(sql):
            if "sales_feedback" in sql:
                return []
            return [
                {"sps_score": 90.0, "bd_decision": "interested"},
                {"sps_score": 80.0, "bd_decision": "interested"},
                {"sps_score": 40.0, "bd_decision": "rejected_unfit"},
            ]

        mock_fetch.side_effect = _fake_fetch
        result = evaluate_sps()
        assert result is not None
        assert result["precision_at_250"] is not None
        assert result["spearman_corr"] is None
        assert result["r2"] is None
        assert result["mae"] is None
        mock_store.assert_called_once()

    @patch("pipeline.model_monitor.fetch_all")
    def test_insufficient_data(self, mock_fetch):
        mock_fetch.return_value = []
        result = evaluate_sps()
        assert result is None


class TestEvaluateModel:
    @patch("pipeline.model_monitor.evaluate_sellability")
    @patch("pipeline.model_monitor.evaluate_sps")
    def test_returns_list(self, mock_sps, mock_sell):
        mock_sell.return_value = {"model_name": "sellability", "recall": 0.9}
        mock_sps.return_value = {"model_name": "sps", "precision_at_250": 0.6}
        results = evaluate_model()
        assert isinstance(results, list)
        assert len(results) == 2
        assert results[0]["model_name"] == "sellability"
        assert results[1]["model_name"] == "sps"

    @patch("pipeline.model_monitor.evaluate_sellability")
    @patch("pipeline.model_monitor.evaluate_sps")
    def test_partial_failure(self, mock_sps, mock_sell):
        mock_sell.return_value = None
        mock_sps.return_value = {"model_name": "sps", "precision_at_250": 0.6}
        results = evaluate_model()
        assert len(results) == 1
        assert results[0]["model_name"] == "sps"
