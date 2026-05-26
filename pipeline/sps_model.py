"""SPS ML 预测模型（Model B）— 统一模型（Ridge / XGBoost），预测销量。

特征：7 维销量相关指标 + creator_type one-hot（6 列）= 13 维。
样本 < 30 用 Ridge，>= 30 用 XGBoost。
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np

from config.settings import (
    CREATOR_TYPES,
    MODEL_META_PATH,
    MODEL_PATH,
    SPS_SALES_NORMALIZER,
)
from db.connection import fetch_all

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "audience_score",
    "engagement_score",
    "virality_score",
    "posting_score",
    "monetization_score",
    "growth_score",
    "audience_segment_score",
]


def _build_feature_vector(row: dict) -> np.ndarray:
    """Build 13-dim feature vector: 7 SPS-related scores + 6 one-hot creator_type."""
    scores = [float(row.get(col) or 0.0) for col in FEATURE_COLS]
    ctype = row.get("creator_type") or "unknown"
    one_hot = [1.0 if ctype == t else 0.0 for t in CREATOR_TYPES]
    return np.array(scores + one_hot)


def _load_training_data() -> tuple[np.ndarray, np.ndarray]:
    """Load seed creators with features + total_sales as (X, y)."""
    rows = fetch_all(
        """SELECT cf.*, c.total_sales,
                  COALESCE(c.creator_type_manual, c.creator_type_auto, 'unknown') AS creator_type
           FROM creator_features cf
           JOIN creators c ON c.id = cf.creator_id
           WHERE c.is_seed = true AND c.total_sales > 0"""
    )
    if not rows:
        raise ValueError("No seed data with features + total_sales found for training")

    X = np.array([_build_feature_vector(r) for r in rows])
    y = np.log1p(np.array([float(r["total_sales"]) for r in rows]))
    return X, y


def train_model() -> dict:
    """Train or retrain the SPS prediction model.

    Returns metadata dict with model_type, n_samples, timestamp, feature_names.
    """
    X, y = _load_training_data()
    n_samples = X.shape[0]

    if n_samples < 30:
        from sklearn.linear_model import Ridge
        model = Ridge(alpha=1.0)
        model_type = "Ridge"
    else:
        from xgboost import XGBRegressor
        model = XGBRegressor(
            n_estimators=50,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.6,
            colsample_bytree=0.6,
            reg_alpha=1.0,
            reg_lambda=2.0,
            random_state=42,
        )
        model_type = "XGBoost"

    model.fit(X, y)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    feature_names = FEATURE_COLS + [f"type_{t}" for t in CREATOR_TYPES]
    meta = {
        "model_type": model_type,
        "n_samples": int(n_samples),
        "n_features": len(feature_names),
        "feature_names": feature_names,
        "target": "total_sales_log1p",
        "sps_sales_normalizer": SPS_SALES_NORMALIZER,
        "trained_at": datetime.utcnow().isoformat(),
    }
    with open(MODEL_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info("Model trained: %s with %d samples", model_type, n_samples)
    return meta


def load_model():
    """Load trained model from disk. Returns None if not available."""
    if not MODEL_PATH.exists():
        logger.warning("No trained model found at %s", MODEL_PATH)
        return None
    return joblib.load(MODEL_PATH)


def sales_to_sps(predicted_sales: float) -> float:
    """Map predicted sales into SPS score (0-100)."""
    raw = float(predicted_sales)
    sps = min(max(raw / SPS_SALES_NORMALIZER, 0.0), 100.0)
    return round(sps, 2)


def predict_sales(features_row: dict) -> float | None:
    """Predict raw sales value for a single creator.

    Args:
        features_row: dict with 7 SPS feature scores + creator_type key.

    Returns:
        Predicted sales (non-negative float), or None if model unavailable.
    """
    model = load_model()
    if model is None:
        return None

    X = _build_feature_vector(features_row).reshape(1, -1)
    log_pred = model.predict(X)[0]
    sales = max(0.0, float(np.expm1(log_pred)))
    return round(sales, 2)


def predict_sps(features_row: dict) -> float | None:
    """Predict SPS score (预测销量评分) for a single creator."""
    sales = predict_sales(features_row)
    if sales is None:
        return None
    return sales_to_sps(sales)


def predict_sales_batch(rows: list[dict]) -> list[float | None]:
    """Predict raw sales values for multiple creators."""
    model = load_model()
    if model is None:
        return [None] * len(rows)

    X = np.array([_build_feature_vector(r) for r in rows])
    log_preds = model.predict(X)
    results: list[float | None] = []
    for p in log_preds:
        sales = max(0.0, float(np.expm1(p)))
        results.append(round(sales, 2))
    return results


def predict_batch(rows: list[dict]) -> list[float | None]:
    """Predict SPS scores for multiple creators (compat wrapper)."""
    sales_batch = predict_sales_batch(rows)
    return [None if s is None else sales_to_sps(s) for s in sales_batch]
    return results
