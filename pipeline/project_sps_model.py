"""项目级销量预测模型（Model Project）。

特征：项目特征（domain one-hot、product_attribute one-hot、price）+
      创作者特征（直接从 projects 表读取，含 is_multi_platform）。
目标：projects.order_quantity。

样本量较小时使用 Ridge，保留所有特征。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import (
    SPS_MODEL_PROJECT_META_PATH,
    SPS_MODEL_PROJECT_PATH,
    SPS_PROJECT_SALES_NORMALIZER,
)
from db.connection import fetch_all

logger = logging.getLogger(__name__)

# 项目特征
PROJECT_CATEGORICAL_FEATURES = {
    "domain": ["OC", "同人", "vtuber", "游戏"],
    "product_attribute": ["普货", "带磁"],
}
PROJECT_NUMERIC_FEATURES = ["price"]

# 创作者特征（直接来自 projects 表列）
CREATOR_FEATURES = [
    "creator_followers_log",
    "creator_following_follower_ratio",
    "creator_avg_daily_posts_30d",
    "creator_reply_engagement_rate",
    "creator_account_age_days_log",
    "creator_has_shop_link",
    "creator_is_nsfw",
    "creator_is_multi_platform",
    "creator_market_tier_high",
    "creator_market_tier_mid",
    "creator_market_tier_low",
    "creator_content_furry",
    "creator_content_anime",
    "creator_content_vtuber",
    "creator_content_gaming",
    "creator_content_webcomic",
    "creator_content_bl",
    "creator_content_gl",
    "creator_content_nsfw",
]


def _build_feature_names() -> list[str]:
    """返回所有特征列名（用于 meta 和可解释性）。"""
    names: list[str] = []
    for col, values in PROJECT_CATEGORICAL_FEATURES.items():
        for v in values:
            names.append(f"{col}_{v}")
    names.extend(PROJECT_NUMERIC_FEATURES)
    names.extend(CREATOR_FEATURES)
    return names


def _build_feature_vector(row: dict) -> np.ndarray:
    """构建项目级特征向量。"""
    features: list[float] = []

    # 1. 项目枚举特征 one-hot
    for col, values in PROJECT_CATEGORICAL_FEATURES.items():
        row_value = str(row.get(col) or "").strip()
        features.extend([1.0 if row_value == v else 0.0 for v in values])

    # 2. 项目数值特征
    for col in PROJECT_NUMERIC_FEATURES:
        features.append(float(row.get(col) or 0.0))

    # 3. 创作者特征
    for col in CREATOR_FEATURES:
        val = row.get(col)
        if val is None:
            features.append(0.0)
        else:
            features.append(float(val))

    return np.array(features)


def _load_training_data() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """加载 projects 表，返回 (X, log_y, raw_quantities)。"""
    feature_cols = ", ".join(CREATOR_FEATURES)
    rows = fetch_all(
        f"""
        SELECT domain, product_attribute, price, order_quantity,
               {feature_cols}
        FROM projects
        WHERE order_quantity > 0
        """
    )
    if not rows:
        raise ValueError("No project data found for training")

    X = np.array([_build_feature_vector(r) for r in rows])
    raw_quantities = np.array([float(r["order_quantity"]) for r in rows])
    y = np.log1p(raw_quantities)
    return X, y, raw_quantities


def train_model() -> dict:
    """训练项目级销量预测模型。

    当前样本量较小，使用 Ridge 回归保留所有特征。

    Returns metadata dict with model_type, n_samples, feature_names, coefficients.
    """
    from sklearn.linear_model import Ridge

    X, y, raw_quantities = _load_training_data()
    n_samples = X.shape[0]

    # 数据驱动的 SPS 归一化基数：训练集 95 分位数
    sales_normalizer = float(np.percentile(raw_quantities, 95))

    feature_names = _build_feature_names()
    if X.shape[1] != len(feature_names):
        raise ValueError(f"Feature dimension mismatch: {X.shape[1]} vs {len(feature_names)}")

    model = Ridge(alpha=1.0)
    model.fit(X, y)
    model_type = "Ridge"

    SPS_MODEL_PROJECT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, SPS_MODEL_PROJECT_PATH)

    coefs = {name: float(coef) for name, coef in zip(feature_names, model.coef_)}
    selected_features = [name for name, coef in coefs.items() if abs(coef) > 1e-6]

    meta = {
        "model_type": model_type,
        "n_samples": int(n_samples),
        "n_features": len(feature_names),
        "feature_names": feature_names,
        "selected_features": selected_features,
        "alpha": float(model.alpha),
        "coefficients": coefs,
        "target": "order_quantity_log1p",
        "sps_project_sales_normalizer": sales_normalizer,
        "trained_at": datetime.utcnow().isoformat(),
        "version": "project_v1",
    }
    with open(SPS_MODEL_PROJECT_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    logger.info(
        "Project-level sales model trained: %s with %d samples, %d features with |coef| > 1e-6",
        model_type, n_samples, len(selected_features),
    )
    return meta


def load_model():
    """Load trained project-level model from disk. Returns None if not available."""
    if not SPS_MODEL_PROJECT_PATH.exists():
        logger.warning("No project-level model found at %s", SPS_MODEL_PROJECT_PATH)
        return None
    return joblib.load(SPS_MODEL_PROJECT_PATH)


def _load_normalizer() -> float:
    """从 meta 文件读取归一化基数，失败则回退到配置默认值。"""
    if SPS_MODEL_PROJECT_META_PATH.exists():
        try:
            with open(SPS_MODEL_PROJECT_META_PATH, encoding="utf-8") as f:
                meta = json.load(f)
            return float(meta.get("sps_project_sales_normalizer", SPS_PROJECT_SALES_NORMALIZER))
        except Exception:
            pass
    return SPS_PROJECT_SALES_NORMALIZER


def sales_to_sps(predicted_sales: float) -> float:
    """Map predicted order quantity into SPS score (0-100)."""
    raw = float(predicted_sales)
    normalizer = _load_normalizer()
    sps = min(max(raw / normalizer, 0.0), 100.0)
    return round(sps, 2)


def predict_sales(features_row: dict) -> float | None:
    """Predict order quantity for a single project."""
    model = load_model()
    if model is None:
        return None

    X = _build_feature_vector(features_row).reshape(1, -1)
    log_pred = model.predict(X)[0]
    sales = max(0.0, float(np.expm1(log_pred)))
    return round(sales, 2)


def predict_sps(features_row: dict) -> float | None:
    """Predict SPS score for a single project."""
    sales = predict_sales(features_row)
    if sales is None:
        return None
    return sales_to_sps(sales)


def predict_sales_batch(rows: list[dict]) -> list[float | None]:
    """Predict order quantities for multiple projects."""
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
    """Predict SPS scores for multiple projects."""
    sales_batch = predict_sales_batch(rows)
    return [None if s is None else sales_to_sps(s) for s in sales_batch]


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        meta = train_model()
        print("Training complete:", meta)
    else:
        print("Usage: python -m pipeline.project_sps_model train")
