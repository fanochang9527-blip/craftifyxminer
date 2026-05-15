"""Unit tests for pipeline.runner — model training integration."""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.runner import train_models


class TestTrainModels:
    @patch("pipeline.sps_model.train_model")
    @patch("pipeline.sellability_model.train_model")
    def test_trains_both_models(self, mock_sell_train, mock_sps_train):
        mock_sell_train.return_value = {
            "model_type": "XGBoostClassifier",
            "n_samples": 150,
        }
        mock_sps_train.return_value = {"model_type": "XGBoost", "n_samples": 50}

        result = train_models()

        assert result["sellability"]["model_type"] == "XGBoostClassifier"
        assert result["sps"]["model_type"] == "XGBoost"
        mock_sell_train.assert_called_once()
        mock_sps_train.assert_called_once()

    @patch("pipeline.sps_model.train_model")
    @patch("pipeline.sellability_model.train_model")
    def test_sellability_failure_continues_to_sps(self, mock_sell_train, mock_sps_train):
        mock_sell_train.side_effect = ValueError("No training data")
        mock_sps_train.return_value = {"model_type": "Ridge", "n_samples": 25}

        result = train_models()

        assert result["sellability"]["error"] == "training_failed"
        assert result["sps"]["model_type"] == "Ridge"
        mock_sell_train.assert_called_once()
        mock_sps_train.assert_called_once()

    @patch("pipeline.sps_model.train_model")
    @patch("pipeline.sellability_model.train_model")
    def test_sps_failure_returns_error(self, mock_sell_train, mock_sps_train):
        mock_sell_train.return_value = {
            "model_type": "LogisticRegression",
            "n_samples": 80,
        }
        mock_sps_train.side_effect = ValueError("No seed data")

        result = train_models()

        assert result["sellability"]["model_type"] == "LogisticRegression"
        assert result["sps"]["error"] == "training_failed"
        mock_sell_train.assert_called_once()
        mock_sps_train.assert_called_once()

    @patch("pipeline.sps_model.train_model")
    @patch("pipeline.sellability_model.train_model")
    def test_both_failures_return_errors(self, mock_sell_train, mock_sps_train):
        mock_sell_train.side_effect = RuntimeError("DB error")
        mock_sps_train.side_effect = RuntimeError("DB error")

        result = train_models()

        assert result["sellability"]["error"] == "training_failed"
        assert result["sps"]["error"] == "training_failed"
