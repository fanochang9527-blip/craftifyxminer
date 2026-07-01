"""训练并对比 Sellability 模型的 LR 与 XGBoost 版本。

用法：
    python scripts/train_sellability_models.py

输出：
    - models/sellability_model_lr.joblib
    - models/sellability_model_lr_meta.json
    - models/sellability_model_xgboost.joblib
    - models/sellability_model_xgboost_meta.json
    - 终端打印两个模型的特征权重/重要性对比
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
from datetime import datetime

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from config.settings import (
    CREATOR_TYPES,
    SELLABILITY_LABEL_SALES_THRESHOLD,
    SELLABILITY_SCORE_THRESHOLD,
)
from db.connection import fetch_all
from pipeline.sellability_model import (
    CONTINUOUS_FEATURE_COLS,
    FEATURE_COLS,
    _build_feature_vector,
)

# 与 pipeline/sellability_model.py 一致的训练数据加载逻辑
def _load_training_rows() -> tuple[list[dict], list[float]]:
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

    if len(rows) < 20:
        seed_labeled = fetch_all(
            """SELECT cf.*, c.id AS creator_id,
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
                 AND c.total_sales >= 0""",
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


def _fit_scaler(X: np.ndarray) -> StandardScaler:
    continuous_idx = [FEATURE_COLS.index(c) for c in CONTINUOUS_FEATURE_COLS]
    scaler = StandardScaler()
    scaler.fit(X[:, continuous_idx])
    return scaler


def _scale(X: np.ndarray, scaler: StandardScaler) -> np.ndarray:
    continuous_idx = [FEATURE_COLS.index(c) for c in CONTINUOUS_FEATURE_COLS]
    X_scaled = X.copy().astype(float)
    X_scaled[:, continuous_idx] = scaler.transform(X[:, continuous_idx])
    return X_scaled


def train_and_save() -> None:
    rows, sample_weights = _load_training_rows()
    X = np.array([_build_feature_vector(r) for r in rows])
    y = np.array([int(r["y"]) for r in rows])
    w = np.array(sample_weights)
    n_samples = X.shape[0]

    scaler = _fit_scaler(X)
    X_scaled = _scale(X, scaler)

    print(f"训练样本: {n_samples}  正例: {int(y.sum())}  负例: {int((1 - y).sum())}")
    print(f"连续特征: {CONTINUOUS_FEATURE_COLS}")
    print()

    models_dir = Path("models")
    models_dir.mkdir(parents=True, exist_ok=True)

    # ---- LogisticRegression ----
    lr = LogisticRegression(max_iter=1000, class_weight="balanced")
    lr.fit(X_scaled, y, sample_weight=w)

    lr_path = models_dir / "sellability_model_lr.joblib"
    joblib.dump({"model": lr, "scaler": scaler}, lr_path)

    lr_meta = {
        "model_type": "LogisticRegression",
        "n_samples": int(n_samples),
        "n_features": len(FEATURE_COLS),
        "feature_names": FEATURE_COLS,
        "n_positive": int(y.sum()),
        "n_negative": int((1 - y).sum()),
        "trained_at": datetime.utcnow().isoformat(),
        "threshold": SELLABILITY_SCORE_THRESHOLD,
        "scaler": {
            "features": CONTINUOUS_FEATURE_COLS,
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
        },
        "intercept": float(lr.intercept_[0]),
        "coefficients": {
            name: float(coef)
            for name, coef in zip(FEATURE_COLS, lr.coef_[0])
        },
    }
    with open(models_dir / "sellability_model_lr_meta.json", "w", encoding="utf-8") as f:
        json.dump(lr_meta, f, indent=2, ensure_ascii=False)

    # ---- XGBoost ----
    xgb = XGBClassifier(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        eval_metric="logloss",
    )
    xgb.fit(X_scaled, y, sample_weight=w)

    xgb_path = models_dir / "sellability_model_xgboost.joblib"
    joblib.dump({"model": xgb, "scaler": scaler}, xgb_path)

    importance_gain = xgb.get_booster().get_score(importance_type="gain")
    importance_weight = xgb.get_booster().get_score(importance_type="weight")
    # XGBoost feature importance 键是 f0, f1, ...，映射回特征名
    xgb_meta = {
        "model_type": "XGBoostClassifier",
        "n_samples": int(n_samples),
        "n_features": len(FEATURE_COLS),
        "feature_names": FEATURE_COLS,
        "n_positive": int(y.sum()),
        "n_negative": int((1 - y).sum()),
        "trained_at": datetime.utcnow().isoformat(),
        "threshold": SELLABILITY_SCORE_THRESHOLD,
        "scaler": {
            "features": CONTINUOUS_FEATURE_COLS,
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
        },
        "importance_gain": {
            FEATURE_COLS[int(k[1:])]: float(v)
            for k, v in importance_gain.items()
        },
        "importance_weight": {
            FEATURE_COLS[int(k[1:])]: float(v)
            for k, v in importance_weight.items()
        },
    }
    with open(models_dir / "sellability_model_xgboost_meta.json", "w", encoding="utf-8") as f:
        json.dump(xgb_meta, f, indent=2, ensure_ascii=False)

    print(f"LR model saved:      {lr_path}")
    print(f"XGBoost model saved: {xgb_path}")
    print()

    # ---- 打印对比 ----
    print("=" * 80)
    print("LR 特征系数（标准化后的权重，正负表示方向）")
    print("=" * 80)
    for name, coef in sorted(
        lr_meta["coefficients"].items(), key=lambda x: abs(x[1]), reverse=True
    ):
        print(f"  {name:30s}: {coef:+.6f}")
    print(f"  {'intercept':30s}: {lr_meta['intercept']:+.6f}")

    print()
    print("=" * 80)
    print("XGBoost 特征重要性（gain）")
    print("=" * 80)
    gain_items = xgb_meta["importance_gain"]
    total_gain = sum(gain_items.values()) or 1.0
    for name, gain in sorted(gain_items.items(), key=lambda x: x[1], reverse=True):
        pct = gain / total_gain * 100
        print(f"  {name:30s}: {gain:10.2f}  ({pct:5.2f}%)")

    print()
    print("=" * 80)
    print("XGBoost 特征使用次数（weight）")
    print("=" * 80)
    weight_items = xgb_meta["importance_weight"]
    for name, wgt in sorted(weight_items.items(), key=lambda x: x[1], reverse=True):
        print(f"  {name:30s}: {wgt:8.0f}")


if __name__ == "__main__":
    train_and_save()
