"""可卖货资格模型（Model A）— 预测“是否值得 BD 联系”。

输出：
- sellability_score: 0-100 概率分
- is_sellable: sellability_score >= SELLABILITY_SCORE_THRESHOLD
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import joblib
import numpy as np

from config.settings import (
    CREATOR_TYPES,
    SELLABILITY_LABEL_SALES_THRESHOLD,
    SELLABILITY_MODEL_META_PATH,
    SELLABILITY_MODEL_PATH,
    SELLABILITY_MODEL_V2_META_PATH,
    SELLABILITY_MODEL_V2_PATH,
    SELLABILITY_SCORE_THRESHOLD,
)
from db.connection import fetch_all
import numpy as np

logger = logging.getLogger(__name__)

# V1：组合特征（控制组，保持现有行为不变）
FEATURE_COLS = [
    "audience_score",
    "engagement_score",
    "monetization_score",
    "growth_score",
    # "character_consistency",
    "community_score",
    "audience_segment_score",
]

# V2：原始拆分特征（实验组，AB 测试用）
# TODO: 当前数据量（BD reviewed ~53 / seed ~142）下 V2 离线 CV 未显著优于 V1。
# 当数据量翻倍（sellability ≥100 / sps ≥300）后重测，若 V2 AUC/Spearman 显著领先再切换。
FEATURE_COLS_V2 = [
    "audience_score",
    "monetization_score",
    # "character_consistency",
    "social_engagement_rate",
    "conversation_rate",
    "fanart_ratio",
    "audience_segment_score",
]


def _build_feature_vector(row: dict) -> np.ndarray:
    """Build 13-dim feature vector: 7 sellability-related scores + 6 one-hot creator_type."""
    scores = [float(row.get(col) or 0.0) for col in FEATURE_COLS]
    ctype = row.get("creator_type") or "unknown"
    one_hot = [1.0 if ctype == t else 0.0 for t in CREATOR_TYPES]
    return np.array(scores + one_hot)


def _build_feature_vector_v2(row: dict) -> np.ndarray:
    """Build 13-dim feature vector (V2): 7 raw scores + 6 one-hot creator_type."""
    scores = [float(row.get(col) or 0.0) for col in FEATURE_COLS_V2]
    ctype = row.get("creator_type") or "unknown"
    one_hot = [1.0 if ctype == t else 0.0 for t in CREATOR_TYPES]
    return np.array(scores + one_hot)


def _load_training_rows() -> tuple[list[dict], list[float]]:
    """Load training rows + sample weights.

    优先使用 BD 人工审核标签；样本不足时回退到规则/AI 伪标签做冷启动。
    """
    reviewed = fetch_all(
        """SELECT cf.*, c.id AS creator_id,
                  COALESCE(c.creator_type_manual, c.creator_type_auto, 'unknown') AS creator_type,
                  CASE
                    WHEN c.bd_decision = 'interested' THEN 1
                    WHEN c.bd_decision IN ('rejected_unfit', 'rejected_not_creator') THEN 0
                    ELSE NULL
                  END AS y
           FROM creator_features cf
           JOIN creators c ON c.id = cf.creator_id
           WHERE c.bd_decision IN ('interested', 'rejected_unfit', 'rejected_not_creator')"""
    )
    rows = [r for r in reviewed if r.get("y") is not None]
    weights = [1.0] * len(rows)
    seen_ids = {int(r["creator_id"]) for r in rows if r.get("creator_id") is not None}

    # 你提供的初始样本规则：total_sales < 50 为负样本，> 50 为正样本（=50 不入样本）
    from pipeline.growth_monitor import is_growth_system_mature

    maturity_filter = ""
    if is_growth_system_mature():
        maturity_filter = "AND cf.growth_score IS DISTINCT FROM 50.0"

    if len(rows) < 20:
        seed_labeled = fetch_all(
            f"""SELECT cf.*, c.id AS creator_id,
                      COALESCE(c.creator_type_manual, c.creator_type_auto, 'unknown') AS creator_type,
                      CASE
                        WHEN c.total_sales > %s THEN 1
                        WHEN c.total_sales < %s THEN 0
                        ELSE NULL
                      END AS y
               FROM creator_features cf
               JOIN creators c ON c.id = cf.creator_id
               WHERE c.is_seed = true
                 AND c.total_sales IS NOT NULL
                 AND c.total_sales >= 0
                 {maturity_filter}""",
            (SELLABILITY_LABEL_SALES_THRESHOLD, SELLABILITY_LABEL_SALES_THRESHOLD),
        )
        for r in seed_labeled:
            if r.get("y") is None or r.get("creator_id") is None:
                continue
            cid = int(r["creator_id"])
            if cid in seen_ids:
                continue
            rows.append(r)
            weights.append(1.0)
            seen_ids.add(cid)

    # 冷启动：当人工标签样本太少，补入弱监督标签
    if len(rows) < 20:
        pseudo = fetch_all(
            """SELECT cf.*, c.id AS creator_id,
                      COALESCE(c.creator_type_manual, c.creator_type_auto, 'unknown') AS creator_type,
                      CASE
                        WHEN c.bd_status IN ('rule_passed', 'ai_passed') THEN 1
                        WHEN c.bd_status IN ('rule_rejected', 'ai_rejected') THEN 0
                        ELSE NULL
                      END AS y
               FROM creator_features cf
               JOIN creators c ON c.id = cf.creator_id
               WHERE c.bd_decision IS NULL
                 AND c.bd_status IN ('rule_passed', 'ai_passed', 'rule_rejected', 'ai_rejected')
               LIMIT 1000"""
        )
        pseudo_rows = [r for r in pseudo if r.get("y") is not None]
        for r in pseudo_rows:
            cid = r.get("creator_id")
            if cid is not None and int(cid) in seen_ids:
                continue
            rows.append(r)
            weights.append(0.35)
            if cid is not None:
                seen_ids.add(int(cid))

    if not rows:
        raise ValueError("No training data found for sellability model")
    return rows, weights


def train_model() -> dict:
    """Train/retrain sellability model."""
    rows, sample_weights = _load_training_rows()
    X = np.array([_build_feature_vector(r) for r in rows])
    y = np.array([int(r["y"]) for r in rows])
    w = np.array(sample_weights)
    n_samples = X.shape[0]
    unique_classes = sorted(set(int(v) for v in y.tolist()))

    # 单类别冷启动：退化为常量分类器，保证流程不中断
    if len(unique_classes) == 1:
        from sklearn.dummy import DummyClassifier

        constant_class = unique_classes[0]
        model = DummyClassifier(strategy="constant", constant=constant_class)
        model.fit(X, y)
        model_type = f"DummyClassifier(constant={constant_class})"
        logger.warning("当前仅单类别，建议补负样本")
    else:
        # 样本少时先用 LogisticRegression，样本足够再切 XGBoostClassifier
        if n_samples < 120:
            from sklearn.linear_model import LogisticRegression

            model = LogisticRegression(max_iter=1000, class_weight="balanced")
            model_type = "LogisticRegression"
        else:
            from xgboost import XGBClassifier

            model = XGBClassifier(
                n_estimators=150,
                max_depth=4,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                eval_metric="logloss",
            )
            model_type = "XGBoostClassifier"

        model.fit(X, y, sample_weight=w)

    SELLABILITY_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, SELLABILITY_MODEL_PATH)

    feature_names = FEATURE_COLS + [f"type_{t}" for t in CREATOR_TYPES]
    meta = {
        "model_type": model_type,
        "n_samples": int(n_samples),
        "n_features": len(feature_names),
        "feature_names": feature_names,
        "n_positive": int(y.sum()),
        "n_negative": int((1 - y).sum()),
        "trained_at": datetime.utcnow().isoformat(),
        "threshold": SELLABILITY_SCORE_THRESHOLD,
    }
    with open(SELLABILITY_MODEL_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info("Sellability model trained: %s (%d samples)", model_type, n_samples)
    return meta


def train_model_v2() -> dict:
    """Train/retrain sellability model (V2 experiment) using raw split features."""
    rows, sample_weights = _load_training_rows()
    X = np.array([_build_feature_vector_v2(r) for r in rows])
    y = np.array([int(r["y"]) for r in rows])
    w = np.array(sample_weights)
    n_samples = X.shape[0]
    unique_classes = sorted(set(int(v) for v in y.tolist()))

    if len(unique_classes) == 1:
        from sklearn.dummy import DummyClassifier

        constant_class = unique_classes[0]
        model = DummyClassifier(strategy="constant", constant=constant_class)
        model.fit(X, y)
        model_type = f"DummyClassifier(constant={constant_class})"
        logger.warning("V2: 当前仅单类别，建议补负样本")
    else:
        if n_samples < 120:
            from sklearn.linear_model import LogisticRegression

            model = LogisticRegression(max_iter=1000, class_weight="balanced")
            model_type = "LogisticRegression"
        else:
            from xgboost import XGBClassifier

            model = XGBClassifier(
                n_estimators=150,
                max_depth=4,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                eval_metric="logloss",
            )
            model_type = "XGBoostClassifier"

        model.fit(X, y, sample_weight=w)

    SELLABILITY_MODEL_V2_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, SELLABILITY_MODEL_V2_PATH)

    feature_names = FEATURE_COLS_V2 + [f"type_{t}" for t in CREATOR_TYPES]
    meta = {
        "model_type": model_type,
        "n_samples": int(n_samples),
        "n_features": len(feature_names),
        "feature_names": feature_names,
        "n_positive": int(y.sum()),
        "n_negative": int((1 - y).sum()),
        "trained_at": datetime.utcnow().isoformat(),
        "threshold": SELLABILITY_SCORE_THRESHOLD,
        "version": "v2_raw_features",
    }
    with open(SELLABILITY_MODEL_V2_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info("Sellability V2 model trained: %s (%d samples)", model_type, n_samples)
    return meta


def load_model():
    """Load trained sellability model; None if unavailable."""
    if not SELLABILITY_MODEL_PATH.exists():
        logger.warning("No sellability model found at %s", SELLABILITY_MODEL_PATH)
        return None
    return joblib.load(SELLABILITY_MODEL_PATH)


def load_model_v2():
    """Load trained sellability V2 model; None if unavailable."""
    if not SELLABILITY_MODEL_V2_PATH.exists():
        logger.warning("No sellability V2 model found at %s", SELLABILITY_MODEL_V2_PATH)
        return None
    return joblib.load(SELLABILITY_MODEL_V2_PATH)


def predict_sellability(features_row: dict) -> float | None:
    """Predict sellability score in 0-100."""
    model = load_model()
    if model is None:
        return None
    X = _build_feature_vector(features_row).reshape(1, -1)
    if hasattr(model, "predict_proba"):
        probs = model.predict_proba(X)[0]
        if getattr(model, "classes_", None) is not None and len(model.classes_) == 1:
            p = 1.0 if int(model.classes_[0]) == 1 else 0.0
        else:
            p = float(probs[1])
    else:
        # fallback for models without predict_proba
        margin = float(model.decision_function(X)[0])
        p = 1.0 / (1.0 + np.exp(-margin))
    return round(max(0.0, min(100.0, p * 100.0)), 2)


def predict_sellability_v2(features_row: dict) -> float | None:
    """Predict sellability score in 0-100 using V2 raw features."""
    model = load_model_v2()
    if model is None:
        return None
    X = _build_feature_vector_v2(features_row).reshape(1, -1)
    if hasattr(model, "predict_proba"):
        probs = model.predict_proba(X)[0]
        if getattr(model, "classes_", None) is not None and len(model.classes_) == 1:
            p = 1.0 if int(model.classes_[0]) == 1 else 0.0
        else:
            p = float(probs[1])
    else:
        margin = float(model.decision_function(X)[0])
        p = 1.0 / (1.0 + np.exp(-margin))
    return round(max(0.0, min(100.0, p * 100.0)), 2)


def predict_batch(rows: list[dict]) -> list[float | None]:
    """Batch predict sellability scores."""
    model = load_model()
    if model is None:
        return [None] * len(rows)
    X = np.array([_build_feature_vector(r) for r in rows])
    if hasattr(model, "predict_proba"):
        probs_raw = model.predict_proba(X)
        if getattr(model, "classes_", None) is not None and len(model.classes_) == 1:
            p = 1.0 if int(model.classes_[0]) == 1 else 0.0
            probs = np.full((X.shape[0],), p)
        else:
            probs = probs_raw[:, 1]
    else:
        margins = model.decision_function(X)
        probs = 1.0 / (1.0 + np.exp(-margins))
    return [round(max(0.0, min(100.0, float(p) * 100.0)), 2) for p in probs]


def predict_batch_v2(rows: list[dict]) -> list[float | None]:
    """Batch predict sellability scores using V2 raw features."""
    model = load_model_v2()
    if model is None:
        return [None] * len(rows)
    X = np.array([_build_feature_vector_v2(r) for r in rows])
    if hasattr(model, "predict_proba"):
        probs_raw = model.predict_proba(X)
        if getattr(model, "classes_", None) is not None and len(model.classes_) == 1:
            p = 1.0 if int(model.classes_[0]) == 1 else 0.0
            probs = np.full((X.shape[0],), p)
        else:
            probs = probs_raw[:, 1]
    else:
        margins = model.decision_function(X)
        probs = 1.0 / (1.0 + np.exp(-margins))
    return [round(max(0.0, min(100.0, float(p) * 100.0)), 2) for p in probs]
