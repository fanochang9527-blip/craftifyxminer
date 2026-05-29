#!/usr/bin/env python3
"""AB Test: V1 组合特征 vs V2 原始拆分特征

离线验证脚本，无需预先跑数据库迁移。
直接从现有 creators + tweets 数据现场计算两组特征，
通过交叉验证对比 sellability 和 sps 两个模型的效果。

Usage:
    .venv/bin/python scripts/ab_test_raw_features.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import logging
from collections import defaultdict

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import KFold, StratifiedKFold
from xgboost import XGBClassifier, XGBRegressor

from config.settings import CREATOR_TYPES, SELLABILITY_LABEL_SALES_THRESHOLD
from db.connection import fetch_all
from pipeline.feature_engine import (
    calc_audience,
    calc_audience_segment,
    calc_character_consistency,
    calc_conversation_rate,
    calc_fanart_ratio,
    calc_monetization,
    calc_monthly_engagement_base,
    calc_posting,
    calc_social_engagement_rate,
    calc_virality,
    calc_virality_raw,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 特征构建
# ------------------------------------------------------------------

V1_SELLABILITY_COLS = [
    "audience_score",
    "engagement_score",
    "monetization_score",
    "growth_score",
    "character_consistency",
    "community_score",
    "audience_segment_score",
]

V2_SELLABILITY_COLS = [
    "audience_score",
    "monetization_score",
    "character_consistency",
    "social_engagement_rate",
    "conversation_rate",
    "fanart_ratio",
    "audience_segment_score",
]

V1_SPS_COLS = [
    "audience_score",
    "engagement_score",
    "virality_score",
    "posting_score",
    "monetization_score",
    "growth_score",
    "audience_segment_score",
]

V2_SPS_COLS = [
    "audience_score",
    "monetization_score",
    "posting_score",
    "virality_raw_ratio",
    "monthly_engagement_base",
    "social_engagement_rate",
    "conversation_rate",
    "audience_segment_score",
]


def _build_vector(row: dict, cols: list[str]) -> np.ndarray:
    scores = [float(row.get(col) or 0.0) for col in cols]
    ctype = row.get("creator_type") or "unknown"
    one_hot = [1.0 if ctype == t else 0.0 for t in CREATOR_TYPES]
    return np.array(scores + one_hot)


def _compute_raw_features_for_creator(creator_id: int) -> dict:
    """从 tweets 现场计算原始拆分特征（不读写数据库）。"""
    creator = fetch_all(
        "SELECT * FROM creators WHERE id = %s", (creator_id,)
    )
    if not creator:
        return {}
    creator = creator[0]

    tweets = fetch_all(
        "SELECT * FROM tweets WHERE creator_id = %s", (creator_id,)
    )

    followers = creator.get("followers") or 0
    bio = creator.get("bio") or ""
    website = creator.get("website") or ""

    # engagement 相关（用于 virality + new features）
    engagement_vals = [
        (t.get("likes") or 0) + (t.get("retweets") or 0) * 2 + (t.get("replies") or 0) * 3
        for t in tweets
    ]
    sorted_eng = sorted(engagement_vals, reverse=True)
    top3_avg = sum(sorted_eng[:3]) / min(len(sorted_eng), 3) if sorted_eng else 0
    monthly_avg = sum(engagement_vals) / len(engagement_vals) if engagement_vals else 0

    audience_segment_score, _ = calc_audience_segment(
        bio, website, creator.get("username") or ""
    )

    return {
        "audience_score": calc_audience(followers, creator.get("following") or 0),
        "engagement_score": 0.0,  # V1 only, not used in V2
        "virality_score": calc_virality(top3_avg, monthly_avg),
        "posting_score": calc_posting(tweets),
        "monetization_score": calc_monetization(bio, website),
        "growth_score": 50.0,
        "character_consistency": calc_character_consistency(tweets),
        "community_score": 0.0,  # V1 only, not used in V2
        "audience_segment_score": audience_segment_score,
        # V2 raw features
        "social_engagement_rate": calc_social_engagement_rate(tweets, followers),
        "conversation_rate": calc_conversation_rate(tweets, followers),
        "fanart_ratio": calc_fanart_ratio(tweets),
        "virality_raw_ratio": calc_virality_raw(top3_avg, monthly_avg),
        "monthly_engagement_base": calc_monthly_engagement_base(monthly_avg),
        "creator_type": creator.get("creator_type_auto") or "unknown",
    }


# ------------------------------------------------------------------
# 数据加载
# ------------------------------------------------------------------

def load_sellability_data() -> tuple[list[dict], list[float]]:
    """复用 sellability_model 的数据加载逻辑。"""
    from pipeline.sellability_model import _load_training_rows

    rows, weights = _load_training_rows()
    return rows, weights


def load_sps_data() -> list[dict]:
    rows = fetch_all(
        """SELECT c.id, c.total_sales,
                  COALESCE(c.creator_type_manual, c.creator_type_auto, 'unknown') AS creator_type
           FROM creators c
           WHERE c.is_seed = true AND c.total_sales > 0"""
    )
    return rows


# ------------------------------------------------------------------
# 模型训练与评估
# ------------------------------------------------------------------

def train_sellability_model(X: np.ndarray, y: np.ndarray, w: np.ndarray):
    n_samples = X.shape[0]
    unique_classes = sorted(set(int(v) for v in y.tolist()))

    if len(unique_classes) == 1:
        model = DummyClassifier(strategy="constant", constant=unique_classes[0])
        model.fit(X, y)
        return model

    if n_samples < 120:
        model = LogisticRegression(max_iter=1000, class_weight="balanced")
    else:
        model = XGBClassifier(
            n_estimators=150, max_depth=4, learning_rate=0.1,
            subsample=0.8, colsample_bytree=0.8, random_state=42,
            eval_metric="logloss",
        )
    model.fit(X, y, sample_weight=w)
    return model


def train_sps_model(X: np.ndarray, y: np.ndarray):
    n_samples = X.shape[0]
    if n_samples < 30:
        model = Ridge(alpha=1.0)
    else:
        model = XGBRegressor(
            n_estimators=50, max_depth=3, learning_rate=0.05,
            subsample=0.6, colsample_bytree=0.6,
            reg_alpha=1.0, reg_lambda=2.0, random_state=42,
        )
    model.fit(X, y)
    return model


def evaluate_sellability(y_true, y_prob) -> dict:
    y_pred = (y_prob >= 0.5).astype(int)
    try:
        auc = float(roc_auc_score(y_true, y_prob))
    except ValueError:
        auc = float("nan")
    return {
        "auc": auc,
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }


def evaluate_sps(y_true, y_pred) -> dict:
    # y_true 和 y_pred 都在 log 空间
    mae = float(mean_absolute_error(y_true, y_pred))
    # 计算 Spearman 相关性（排序一致性）
    from scipy.stats import spearmanr

    corr, _ = spearmanr(y_true, y_pred)
    return {"mae": mae, "spearman": float(corr) if not np.isnan(corr) else float("nan")}


# ------------------------------------------------------------------
# AB Test 主逻辑
# ------------------------------------------------------------------

def ab_test_sellability(n_splits: int = 5):
    logger.info("=" * 70)
    logger.info("Sellability Model AB Test: V1 (组合特征) vs V2 (原始拆分特征)")
    logger.info("=" * 70)

    rows, weights = load_sellability_data()
    logger.info(f"训练样本: {len(rows)}  (BD reviewed + seed fallback)")

    # 为每个样本现场计算两组特征
    X_v1, X_v2, y, w = [], [], [], []
    for i, r in enumerate(rows):
        cid = int(r["creator_id"])
        feats = _compute_raw_features_for_creator(cid)
        if not feats:
            continue
        # V1 需要补充 V1-only 字段
        feats["engagement_score"] = r.get("engagement_score") or 0.0
        feats["community_score"] = r.get("community_score") or 0.0
        feats["creator_type"] = r.get("creator_type") or "unknown"

        X_v1.append(_build_vector(feats, V1_SELLABILITY_COLS))
        X_v2.append(_build_vector(feats, V2_SELLABILITY_COLS))
        y.append(int(r["y"]))
        w.append(weights[i])

    X_v1 = np.array(X_v1)
    X_v2 = np.array(X_v2)
    y = np.array(y)
    w = np.array(w)
    logger.info(f"有效样本: {len(y)}  正例: {int(y.sum())}  负例: {int((1 - y).sum())}")

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    results = defaultdict(lambda: defaultdict(list))

    for fold, (train_idx, test_idx) in enumerate(skf.split(X_v1, y), 1):
        for name, X in [("V1", X_v1), ("V2", X_v2)]:
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
            w_train = w[train_idx]

            model = train_sellability_model(X_train, y_train, w_train)
            if hasattr(model, "predict_proba"):
                y_prob = model.predict_proba(X_test)[:, 1]
            else:
                margins = model.decision_function(X_test)
                y_prob = 1.0 / (1.0 + np.exp(-margins))

            metrics = evaluate_sellability(y_test, y_prob)
            for k, v in metrics.items():
                results[name][k].append(v)

            logger.info(f"Fold {fold} | {name:3s} | " + " | ".join(f"{k}={v:.4f}" for k, v in metrics.items()))

    logger.info("-" * 70)
    logger.info(f"{'Version':8s} | {'AUC':>10s} | {'Accuracy':>10s} | {'Precision':>10s} | {'Recall':>10s} | {'F1':>10s}")
    logger.info("-" * 70)
    for name in ["V1", "V2"]:
        means = {k: np.nanmean(vs) for k, vs in results[name].items()}
        stds = {k: np.nanstd(vs) for k, vs in results[name].items()}
        logger.info(
            f"{name:8s} | {means['auc']:>5.4f}±{stds['auc']:>4.4f} | "
            f"{means['accuracy']:>5.4f}±{stds['accuracy']:>4.4f} | "
            f"{means['precision']:>5.4f}±{stds['precision']:>4.4f} | "
            f"{means['recall']:>5.4f}±{stds['recall']:>4.4f} | "
            f"{means['f1']:>5.4f}±{stds['f1']:>4.4f}"
        )

    v1_auc = np.nanmean(results["V1"]["auc"])
    v2_auc = np.nanmean(results["V2"]["auc"])
    delta = v2_auc - v1_auc
    logger.info("-" * 70)
    if delta > 0:
        logger.info(f"结论: V2 AUC 更高，领先 {delta:.4f}")
    else:
        logger.info(f"结论: V1 AUC 更高，领先 {-delta:.4f}")
    logger.info("=" * 70)
    logger.info("NOTE: 当前数据量下若 V2 未显著领先，请勿切换主模型。")
    logger.info("      待数据翻倍（sellability≥100 / sps≥300）后重新运行此脚本评估。")
    logger.info("=" * 70)
    return dict(results)


def ab_test_sps(n_splits: int = 5):
    logger.info("")
    logger.info("=" * 70)
    logger.info("SPS Model AB Test: V1 (组合特征) vs V2 (原始拆分特征)")
    logger.info("=" * 70)

    rows = load_sps_data()
    logger.info(f"训练样本: {len(rows)}  (seed creators with total_sales > 0)")

    X_v1, X_v2, y = [], [], []
    for r in rows:
        cid = int(r["id"])
        feats = _compute_raw_features_for_creator(cid)
        if not feats:
            continue
        # V1 需要补充 V1-only 字段
        feats["engagement_score"] = 0.0
        feats["community_score"] = 0.0
        feats["creator_type"] = r.get("creator_type") or "unknown"

        X_v1.append(_build_vector(feats, V1_SPS_COLS))
        X_v2.append(_build_vector(feats, V2_SPS_COLS))
        y.append(float(r["total_sales"]))

    X_v1 = np.array(X_v1)
    X_v2 = np.array(X_v2)
    y = np.log1p(np.array(y))
    logger.info(f"有效样本: {len(y)}")

    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    results = defaultdict(lambda: defaultdict(list))

    for fold, (train_idx, test_idx) in enumerate(kf.split(X_v1), 1):
        for name, X in [("V1", X_v1), ("V2", X_v2)]:
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]

            model = train_sps_model(X_train, y_train)
            y_pred = model.predict(X_test)

            metrics = evaluate_sps(y_test, y_pred)
            for k, v in metrics.items():
                results[name][k].append(v)

            logger.info(f"Fold {fold} | {name:3s} | MAE={metrics['mae']:.4f} | Spearman={metrics['spearman']:.4f}")

    logger.info("-" * 70)
    logger.info(f"{'Version':8s} | {'MAE (log)':>12s} | {'Spearman':>12s}")
    logger.info("-" * 70)
    for name in ["V1", "V2"]:
        means = {k: np.nanmean(vs) for k, vs in results[name].items()}
        stds = {k: np.nanstd(vs) for k, vs in results[name].items()}
        logger.info(
            f"{name:8s} | {means['mae']:>5.4f}±{stds['mae']:>4.4f} | "
            f"{means['spearman']:>5.4f}±{stds['spearman']:>4.4f}"
        )

    v1_spear = np.nanmean(results["V1"]["spearman"])
    v2_spear = np.nanmean(results["V2"]["spearman"])
    delta = v2_spear - v1_spear
    logger.info("-" * 70)
    if delta > 0:
        logger.info(f"结论: V2 Spearman 更高，领先 {delta:.4f}")
    else:
        logger.info(f"结论: V1 Spearman 更高，领先 {-delta:.4f}")
    logger.info("=" * 70)
    return dict(results)


if __name__ == "__main__":
    ab_test_sellability()
    ab_test_sps()
