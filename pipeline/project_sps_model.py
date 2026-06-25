"""项目级销量预测模型（Model Project）。

特征：项目枚举特征（domain、product_attribute 单值整数编码）+ price +
      创作者枚举特征（creator_market_tier 单值整数编码）+
      创作者数值/布尔特征（直接从 projects 表读取）。
目标：projects.order_quantity。

将同一业务字段的互斥选项编码为单个整数特征，让 Ridge 感知其互斥关系。
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

# 项目枚举特征：同一字段的互斥选项映射为单个整数，让模型感知互斥关系
PROJECT_ENUM_FEATURES = {
    "domain": {"OC": 0, "同人": 1, "vtuber": 2, "游戏": 3},
    "product_attribute": {"普货": 0, "带磁": 1},
}
PROJECT_NUMERIC_FEATURES = ["price"]

# 创作者枚举特征：市场层级映射为单个整数（存在自然顺序）
CREATOR_ENUM_FEATURES = {
    "creator_market_tier": {"low": 0, "mid": 1, "high": 2},
}

# 创作者数值/布尔特征（直接来自 projects 表列）
# 注：内容分类特征（creator_content_*）已暂时停用，保留计算代码但不入模；
#     creator_reply_engagement_rate / creator_avg_daily_posts_30d 已从模型中移除。
CREATOR_FEATURES = [
    "creator_followers_log",
    "creator_following_follower_ratio",
    "creator_account_age_days_log",
    "creator_has_shop_link",
    "creator_is_nsfw",
    "creator_is_multi_platform",
]


def _build_feature_names() -> list[str]:
    """返回所有特征列名（用于 meta 和可解释性）。"""
    names: list[str] = []
    names.extend(PROJECT_ENUM_FEATURES.keys())
    names.extend(PROJECT_NUMERIC_FEATURES)
    names.extend(CREATOR_ENUM_FEATURES.keys())
    names.extend(CREATOR_FEATURES)
    return names


def _encode_enum(value: object, mapping: dict[str, int]) -> float:
    """将枚举值映射为整数；未知/空值编码为 -1，便于模型区分缺失。"""
    key = str(value or "").strip().lower()
    return float(mapping.get(key, -1.0))


def _build_feature_vector(row: dict) -> np.ndarray:
    """构建项目级特征向量。"""
    features: list[float] = []

    # 1. 项目枚举特征（单值整数编码，表达互斥关系）
    for col, mapping in PROJECT_ENUM_FEATURES.items():
        features.append(_encode_enum(row.get(col), mapping))

    # 2. 项目数值特征
    for col in PROJECT_NUMERIC_FEATURES:
        features.append(float(row.get(col) or 0.0))

    # 3. 创作者枚举特征
    for col, mapping in CREATOR_ENUM_FEATURES.items():
        features.append(_encode_enum(row.get(col), mapping))

    # 4. 创作者数值/布尔特征
    for col in CREATOR_FEATURES:
        val = row.get(col)
        if val is None:
            features.append(0.0)
        else:
            features.append(float(val))

    return np.array(features)


def _load_training_data() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """加载 projects 表，返回 (X, log_y, raw_quantities)。"""
    creator_cols = list(CREATOR_ENUM_FEATURES.keys()) + CREATOR_FEATURES
    feature_cols = ", ".join(creator_cols)
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

    样本量 >= 30 时使用 XGBoost，利用枚举特征的互斥关系；
    样本量 < 30 时回退到 Ridge 保证小样本稳定性。

    Returns metadata dict with model_type, n_samples, feature_names, coefficients/importances.
    """
    X, y, raw_quantities = _load_training_data()
    n_samples = X.shape[0]

    # 数据驱动的 SPS 归一化基数：训练集 95 分位数
    sales_normalizer = float(np.percentile(raw_quantities, 95))

    feature_names = _build_feature_names()
    if X.shape[1] != len(feature_names):
        raise ValueError(f"Feature dimension mismatch: {X.shape[1]} vs {len(feature_names)}")

    if n_samples < 30:
        from sklearn.linear_model import Ridge

        model = Ridge(alpha=1.0)
        model.fit(X, y)
        model_type = "Ridge"
        alpha = float(model.alpha)
        coefs = {name: float(coef) for name, coef in zip(feature_names, model.coef_)}
        importances: dict[str, float] | None = None
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
        model.fit(X, y)
        model_type = "XGBoost"
        alpha = None
        coefs = None
        importances = {
            name: float(imp)
            for name, imp in zip(feature_names, model.feature_importances_)
        }

    SPS_MODEL_PROJECT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, SPS_MODEL_PROJECT_PATH)

    selected_features = [
        name
        for name in feature_names
        if (coefs is None or abs(coefs[name]) > 1e-6)
        and (importances is None or importances[name] > 1e-6)
    ]

    meta: dict = {
        "model_type": model_type,
        "n_samples": int(n_samples),
        "n_features": len(feature_names),
        "feature_names": feature_names,
        "selected_features": selected_features,
        "enum_mappings": {
            "project": PROJECT_ENUM_FEATURES,
            "creator": CREATOR_ENUM_FEATURES,
        },
        "target": "order_quantity_log1p",
        "sps_project_sales_normalizer": sales_normalizer,
        "trained_at": datetime.utcnow().isoformat(),
        "version": "project_v3",
    }
    if alpha is not None:
        meta["alpha"] = alpha
    if coefs is not None:
        meta["coefficients"] = coefs
    if importances is not None:
        meta["feature_importances"] = importances

    with open(SPS_MODEL_PROJECT_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    logger.info(
        "Project-level sales model trained: %s with %d samples, %d selected features",
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
