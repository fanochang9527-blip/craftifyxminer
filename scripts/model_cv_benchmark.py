"""模型交叉验证基准脚本 — 对比不同特征维度/策略的精度。

用法：
    python scripts/model_cv_benchmark.py

输出：
    Sellability 和 SPS 模型在旧 15 维 vs 新 13 维特征下的 5-Fold CV 对比。
"""

import sys
from pathlib import Path

# 将项目根目录加入路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from config.settings import CREATOR_TYPES
from db.connection import fetch_all
from pipeline.sellability_model import _load_training_rows

# ------------------------------------------------------------------
# 特征定义
# ------------------------------------------------------------------
OLD_FEATURE_COLS = [
    "audience_score",
    "engagement_score",
    "virality_score",
    "posting_score",
    "monetization_score",
    "growth_score",
    # "character_consistency",
    "community_score",
    "audience_segment_score",
]

SPS_FEATURE_COLS = [
    "audience_score",
    "engagement_score",
    "virality_score",
    "posting_score",
    "monetization_score",
    "growth_score",
    "audience_segment_score",
]

SELLABILITY_FEATURE_COLS = [
    "audience_score",
    "has_monetization_signal",
    # "growth_score",
    # "character_consistency",
    "social_engagement_rate",
    "conversation_rate",
    "fanart_ratio",
    "mention_rate",
    "retweet_rate",
    "audience_is_nsfw",
    "audience_is_multi_platform",
]


def _build_vector(row: dict, cols: list[str]) -> np.ndarray:
    scores = [float(row.get(col) or 0.0) for col in cols]
    ctype = row.get("creator_type") or "unknown"
    one_hot = [1.0 if ctype == t else 0.0 for t in CREATOR_TYPES]
    return np.array(scores + one_hot)


def _print_divider(title: str) -> None:
    print("=" * 60)
    print(title)
    print("=" * 60)


def _scale_continuous(X_train: np.ndarray, X_test: np.ndarray, cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """对连续特征做 StandardScaler，布尔/ordinal 特征保持原值。"""
    categorical = {"has_monetization_signal", "audience_is_nsfw", "audience_is_multi_platform", "creator_type"}
    continuous_idx = [i for i, c in enumerate(cols) if c not in categorical]
    scaler = StandardScaler()
    X_train_scaled = X_train.copy()
    X_test_scaled = X_test.copy()
    X_train_scaled[:, continuous_idx] = scaler.fit_transform(X_train[:, continuous_idx])
    X_test_scaled[:, continuous_idx] = scaler.transform(X_test[:, continuous_idx])
    return X_train_scaled, X_test_scaled


def cv_sellability() -> None:
    rows, _weights = _load_training_rows()
    y = np.array([int(r["y"]) for r in rows])

    for name, cols in [
        ("旧 15 维统一特征", OLD_FEATURE_COLS),
        ("新 13 维拆分特征", SELLABILITY_FEATURE_COLS),
    ]:
        X = np.array([_build_vector(r, cols) for r in rows])
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        accs, precs, recs, f1s = [], [], [], []
        for train_idx, test_idx in skf.split(X, y):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
            X_train, X_test = _scale_continuous(X_train, X_test, cols)
            model = LogisticRegression(max_iter=1000, class_weight="balanced")
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            accs.append(accuracy_score(y_test, y_pred))
            precs.append(precision_score(y_test, y_pred, zero_division=0))
            recs.append(recall_score(y_test, y_pred, zero_division=0))
            f1s.append(f1_score(y_test, y_pred, zero_division=0))

        print(f"\n{name}:")
        print(f"  准确率: {np.mean(accs):.4f} (±{np.std(accs):.4f})")
        print(f"  精确率: {np.mean(precs):.4f} (±{np.std(precs):.4f})")
        print(f"  召回率: {np.mean(recs):.4f} (±{np.std(recs):.4f})")
        print(f"  F1:     {np.mean(f1s):.4f} (±{np.std(f1s):.4f})")
        print(f"  各折 F1: {[round(f, 4) for f in f1s]}")


def cv_sps() -> None:
    sps_raw = fetch_all(
        """
        SELECT cf.*, c.total_sales,
               COALESCE(c.creator_type_manual, c.creator_type_auto, 'unknown') AS creator_type
        FROM creator_features cf
        JOIN creators c ON c.id = cf.creator_id
        WHERE c.is_seed = true AND c.total_sales > 0
        """
    )

    for name, cols, use_ridge in [
        ("旧 15 维统一特征 (Ridge)", OLD_FEATURE_COLS, True),
        ("新 13 维拆分特征 (Ridge)", SPS_FEATURE_COLS, True),
        ("旧 15 维统一特征 (XGBoost)", OLD_FEATURE_COLS, False),
        ("新 13 维拆分特征 (XGBoost)", SPS_FEATURE_COLS, False),
    ]:
        X = np.array([_build_vector(r, cols) for r in sps_raw])
        y = np.log1p(np.array([float(r["total_sales"]) for r in sps_raw]))
        kf = KFold(n_splits=5, shuffle=True, random_state=42)
        maes, rmses, r2s = [], [], []
        for train_idx, test_idx in kf.split(X):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
            if use_ridge:
                model = Ridge(alpha=1.0)
            else:
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
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            maes.append(mean_absolute_error(np.expm1(y_test), np.expm1(y_pred)))
            rmses.append(np.sqrt(mean_squared_error(np.expm1(y_test), np.expm1(y_pred))))
            r2s.append(r2_score(np.expm1(y_test), np.expm1(y_pred)))

        print(f"\n{name}:")
        print(f"  MAE:  {np.mean(maes):.2f} (±{np.std(maes):.2f})")
        print(f"  RMSE: {np.mean(rmses):.2f} (±{np.std(rmses):.2f})")
        print(f"  R²:   {np.mean(r2s):.4f} (±{np.std(r2s):.4f})")
        print(f"  各折 R²: {[round(r, 4) for r in r2s]}")


if __name__ == "__main__":
    _print_divider("Sellability 模型 — 5 折 Stratified 交叉验证")
    cv_sellability()

    print()
    _print_divider("SPS 模型 — 5 折交叉验证")
    cv_sps()
