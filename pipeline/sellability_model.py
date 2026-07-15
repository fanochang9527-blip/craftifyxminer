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

logger = logging.getLogger(__name__)

# V1：原始拆分特征直接入模，不再使用人工设定系数的组合特征
# FIXME: 临时停用 growth_score，待历史粉丝快照积累足够后重新启用
FEATURE_COLS = [
    "audience_score",
    "has_monetization_signal",
    # "growth_score",
    # "character_consistency",
    "social_engagement_rate",
    "conversation_rate",
    "fanart_ratio",
    "mention_rate",
    "retweet_rate",
    "days_since_last_post",
    "audience_is_nsfw",
    "audience_is_multi_platform",
    "creator_type",
]

# V2：原始拆分特征（实验组，AB 测试用）
# TODO: 当前数据量（BD reviewed ~53 / seed ~142）下 V2 离线 CV 未显著优于 V1。
# 当数据量翻倍（sellability ≥100 / sps ≥300）后重测，若 V2 AUC/Spearman 显著领先再切换。
FEATURE_COLS_V2 = [
    "audience_score",
    "has_monetization_signal",
    # "character_consistency",
    "social_engagement_rate",
    "conversation_rate",
    "fanart_ratio",
    "mention_rate",
    "retweet_rate",
    "days_since_last_post",
    "audience_is_nsfw",
    "audience_is_multi_platform",
    "creator_type",
]

# 需要对连续特征做 StandardScaler 标准化；布尔/ordinal 特征保持 0/1 不变。
CONTINUOUS_FEATURE_COLS = [
    "audience_score",
    "social_engagement_rate",
    "conversation_rate",
    "fanart_ratio",
    "mention_rate",
    "retweet_rate",
    "days_since_last_post",
]
CONTINUOUS_FEATURE_IDX = [FEATURE_COLS.index(c) for c in CONTINUOUS_FEATURE_COLS]
# V2 与 V1 特征顺序相同，因此连续特征索引也相同。


def _creator_type_ordinal(ctype: str | None) -> float:
    """Map creator type to an ordinal integer so the model sees a single
    mutually-exclusive categorical feature instead of 6 one-hot columns.
    Unknown types fall back to the last index.
    """
    return float(CREATOR_TYPES.index(ctype)) if ctype in CREATOR_TYPES else float(CREATOR_TYPES.index("unknown"))


def _build_feature_vector(row: dict) -> np.ndarray:
    """Build 11-dim feature vector: 10 raw/sellability signals + 1 ordinal creator_type.

    - engagement_score 已拆分为 social_engagement_rate 与 conversation_rate
    - audience_segment_score 已拆分为 audience_is_nsfw 与 audience_is_multi_platform
    - monetization_score 已替换为 has_monetization_signal
    - community_score 已拆分为 fanart_ratio / mention_rate / retweet_rate
    - days_since_last_post 表示最近发帖距今天数，越小越活跃
    由模型自行学习权重，不再使用人工设定的组合分数。
    """
    scores = [float(row.get(col) or 0.0) for col in FEATURE_COLS if col != "creator_type"]
    scores.append(_creator_type_ordinal(row.get("creator_type")))
    return np.array(scores)


def _build_feature_vector_v2(row: dict) -> np.ndarray:
    """Build 11-dim feature vector (V2): 10 raw signals + 1 ordinal creator_type."""
    scores = [float(row.get(col) or 0.0) for col in FEATURE_COLS_V2 if col != "creator_type"]
    scores.append(_creator_type_ordinal(row.get("creator_type")))
    return np.array(scores)


def _fit_scaler(X: np.ndarray) -> "StandardScaler":
    """Fit StandardScaler on continuous feature columns only."""
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    scaler.fit(X[:, CONTINUOUS_FEATURE_IDX])
    return scaler


def _scale_features(X: np.ndarray, scaler: "StandardScaler | None") -> np.ndarray:
    """Apply fitted StandardScaler to continuous columns; leave bool/ordinal untouched."""
    if scaler is None:
        return X
    X_scaled = X.copy().astype(float)
    X_scaled[:, CONTINUOUS_FEATURE_IDX] = scaler.transform(X[:, CONTINUOUS_FEATURE_IDX])
    return X_scaled


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
    # FIXME: 临时停用 growth_score 成熟度过滤，待历史粉丝快照积累足够后重新启用
    # from pipeline.growth_monitor import is_growth_system_mature

    # maturity_filter = ""
    # if is_growth_system_mature():
    #     maturity_filter = "AND cf.growth_score IS DISTINCT FROM 50.0"
    maturity_filter = ""

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

    # 对连续特征做标准化；布尔/ordinal 特征保持原值
    scaler = _fit_scaler(X)
    X_scaled = _scale_features(X, scaler)

    # 单类别冷启动：退化为常量分类器，保证流程不中断
    if len(unique_classes) == 1:
        from sklearn.dummy import DummyClassifier

        constant_class = unique_classes[0]
        model = DummyClassifier(strategy="constant", constant=constant_class)
        model.fit(X_scaled, y)
        model_type = f"DummyClassifier(constant={constant_class})"
        logger.warning("当前仅单类别，建议补负样本")
    else:
        # AB 测试显示 XGBoost 在 recall/F1/ROC-AUC 上均优于 LogisticRegression，
        # 因此生产模型固定使用 XGBoostClassifier。
        # 超参数经 5-fold CV 调优（213 样本 / 11 维特征）：
        #   n_estimators=80, max_depth=3, lr=0.05, subsample=1.0, colsample_bytree=0.8
        from xgboost import XGBClassifier

        model = XGBClassifier(
            n_estimators=80,
            max_depth=3,
            learning_rate=0.05,
            subsample=1.0,
            colsample_bytree=0.8,
            random_state=42,
            eval_metric="logloss",
        )
        model_type = "XGBoostClassifier"
        model.fit(X_scaled, y, sample_weight=w)

    SELLABILITY_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "scaler": scaler}, SELLABILITY_MODEL_PATH)

    feature_names = FEATURE_COLS
    meta = {
        "model_type": model_type,
        "n_samples": int(n_samples),
        "n_features": len(feature_names),
        "feature_names": feature_names,
        "n_positive": int(y.sum()),
        "n_negative": int((1 - y).sum()),
        "trained_at": datetime.utcnow().isoformat(),
        "threshold": SELLABILITY_SCORE_THRESHOLD,
        "scaler": {
            "features": CONTINUOUS_FEATURE_COLS,
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
        },
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

    # V2 与 V1 连续特征顺序相同，共用同一套 scaler 索引
    scaler = _fit_scaler(X)
    X_scaled = _scale_features(X, scaler)

    if len(unique_classes) == 1:
        from sklearn.dummy import DummyClassifier

        constant_class = unique_classes[0]
        model = DummyClassifier(strategy="constant", constant=constant_class)
        model.fit(X_scaled, y)
        model_type = f"DummyClassifier(constant={constant_class})"
        logger.warning("V2: 当前仅单类别，建议补负样本")
    else:
        from xgboost import XGBClassifier

        model = XGBClassifier(
            n_estimators=80,
            max_depth=3,
            learning_rate=0.05,
            subsample=1.0,
            colsample_bytree=0.8,
            random_state=42,
            eval_metric="logloss",
        )
        model_type = "XGBoostClassifier"
        model.fit(X_scaled, y, sample_weight=w)

    SELLABILITY_MODEL_V2_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "scaler": scaler}, SELLABILITY_MODEL_V2_PATH)

    feature_names = FEATURE_COLS_V2
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
        "scaler": {
            "features": CONTINUOUS_FEATURE_COLS,
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
        },
    }
    with open(SELLABILITY_MODEL_V2_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info("Sellability V2 model trained: %s (%d samples)", model_type, n_samples)
    return meta


def load_model() -> dict | None:
    """Load trained sellability model payload {'model': ..., 'scaler': ...}.

    兼容旧格式：仅保存了 model 对象的 joblib 会包装成 {'model': model, 'scaler': None}。
    """
    if not SELLABILITY_MODEL_PATH.exists():
        logger.warning("No sellability model found at %s", SELLABILITY_MODEL_PATH)
        return None
    payload = joblib.load(SELLABILITY_MODEL_PATH)
    if isinstance(payload, dict):
        return payload
    return {"model": payload, "scaler": None}


def load_model_v2() -> dict | None:
    """Load trained sellability V2 model payload."""
    if not SELLABILITY_MODEL_V2_PATH.exists():
        logger.warning("No sellability V2 model found at %s", SELLABILITY_MODEL_V2_PATH)
        return None
    payload = joblib.load(SELLABILITY_MODEL_V2_PATH)
    if isinstance(payload, dict):
        return payload
    return {"model": payload, "scaler": None}


def predict_sellability(features_row: dict) -> float | None:
    """Predict sellability score in 0-100."""
    payload = load_model()
    if payload is None:
        return None
    model = payload["model"]
    scaler = payload.get("scaler")
    X = _scale_features(_build_feature_vector(features_row).reshape(1, -1), scaler)
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
    payload = load_model_v2()
    if payload is None:
        return None
    model = payload["model"]
    scaler = payload.get("scaler")
    X = _scale_features(_build_feature_vector_v2(features_row).reshape(1, -1), scaler)
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
    payload = load_model()
    if payload is None:
        return [None] * len(rows)
    model = payload["model"]
    scaler = payload.get("scaler")
    X = _scale_features(np.array([_build_feature_vector(r) for r in rows]), scaler)
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
    payload = load_model_v2()
    if payload is None:
        return [None] * len(rows)
    model = payload["model"]
    scaler = payload.get("scaler")
    X = _scale_features(np.array([_build_feature_vector_v2(r) for r in rows]), scaler)
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
