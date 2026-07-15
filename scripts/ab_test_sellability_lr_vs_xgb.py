"""AB 测试：Sellability 模型 LR vs XGBoost（当前 11 维特征 + StandardScaler）。

用法：
    python scripts/ab_test_sellability_lr_vs_xgb.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import logging

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from xgboost import XGBClassifier

from pipeline.sellability_model import (
    CONTINUOUS_FEATURE_COLS,
    FEATURE_COLS,
    _build_feature_vector,
    _load_training_rows,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _scale_continuous(X_train: np.ndarray, X_test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.preprocessing import StandardScaler

    continuous_idx = [FEATURE_COLS.index(c) for c in CONTINUOUS_FEATURE_COLS]
    scaler = StandardScaler()
    X_train_scaled = X_train.copy()
    X_test_scaled = X_test.copy()
    X_train_scaled[:, continuous_idx] = scaler.fit_transform(X_train[:, continuous_idx])
    X_test_scaled[:, continuous_idx] = scaler.transform(X_test[:, continuous_idx])
    return X_train_scaled, X_test_scaled


def _train_lr(X_train, y_train, w_train):
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X_train, y_train, sample_weight=w_train)
    return model


def _train_xgb(X_train, y_train, w_train):
    model = XGBClassifier(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        eval_metric="logloss",
    )
    model.fit(X_train, y_train, sample_weight=w_train)
    return model


def _eval(model, X_test, y_test):
    if hasattr(model, "predict_proba"):
        y_prob = model.predict_proba(X_test)[:, 1]
    else:
        margins = model.decision_function(X_test)
        y_prob = 1.0 / (1.0 + np.exp(-margins))
    y_pred = (y_prob >= 0.5).astype(int)
    return {
        "accuracy": accuracy_score(y_test, y_pred),
        "precision": precision_score(y_test, y_pred, zero_division=0),
        "recall": recall_score(y_test, y_pred, zero_division=0),
        "f1": f1_score(y_test, y_pred, zero_division=0),
        "roc_auc": roc_auc_score(y_test, y_prob),
    }


def main(n_splits: int = 5):
    rows, weights = _load_training_rows()
    X = np.array([_build_feature_vector(r) for r in rows])
    y = np.array([int(r["y"]) for r in rows])
    w = np.array(weights)

    logger.info(f"样本: {len(y)}  正例: {int(y.sum())}  负例: {int((1 - y).sum())}")

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    results = {"LR": [], "XGBoost": []}

    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y), 1):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        w_train = w[train_idx]

        X_train_s, X_test_s = _scale_continuous(X_train, X_test)

        for name, train_fn in [("LR", _train_lr), ("XGBoost", _train_xgb)]:
            model = train_fn(X_train_s, y_train, w_train)
            metrics = _eval(model, X_test_s, y_test)
            results[name].append(metrics)
            logger.info(f"Fold {fold} {name}: {metrics}")

    print()
    print("=" * 80)
    print(f"Sellability AB Test: LR vs XGBoost ({n_splits}-fold CV)")
    print("=" * 80)
    for name in ["LR", "XGBoost"]:
        print(f"\n{name}:")
        for metric in ["accuracy", "precision", "recall", "f1", "roc_auc"]:
            values = [m[metric] for m in results[name]]
            mean = np.mean(values)
            std = np.std(values)
            print(f"  {metric:12s}: {mean:.4f} (+/- {std:.4f})")

    # Save results
    out_path = Path("models/ab_test_lr_vs_xgb.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
