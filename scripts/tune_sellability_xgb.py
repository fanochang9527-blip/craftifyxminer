"""XGBoost 超参数调优（当前 10 维特征，213 样本）。

用法：
    python scripts/tune_sellability_xgb.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import itertools
import json
import logging

import numpy as np
from sklearn.metrics import f1_score, roc_auc_score
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


def evaluate(params: dict, X: np.ndarray, y: np.ndarray, w: np.ndarray, n_splits: int = 5) -> dict:
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    f1s, aucs = [], []
    for train_idx, test_idx in skf.split(X, y):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        w_train = w[train_idx]

        X_train_s, X_test_s = _scale_continuous(X_train, X_test)

        model = XGBClassifier(**params, eval_metric="logloss", random_state=42)
        model.fit(X_train_s, y_train, sample_weight=w_train)
        prob = model.predict_proba(X_test_s)[:, 1]
        pred = (prob >= 0.5).astype(int)
        f1s.append(f1_score(y_test, pred, zero_division=0))
        aucs.append(roc_auc_score(y_test, prob))

    return {
        "f1_mean": float(np.mean(f1s)),
        "f1_std": float(np.std(f1s)),
        "auc_mean": float(np.mean(aucs)),
        "auc_std": float(np.std(aucs)),
    }


def main():
    rows, weights = _load_training_rows()
    X = np.array([_build_feature_vector(r) for r in rows])
    y = np.array([int(r["y"]) for r in rows])
    w = np.array(weights)

    logger.info(f"样本: {len(y)}  正例: {int(y.sum())}  负例: {int((1 - y).sum())}")

    param_grid = {
        "n_estimators": [80, 120, 150],
        "max_depth": [2, 3, 4],
        "learning_rate": [0.05, 0.1, 0.15],
        "subsample": [0.8, 0.9, 1.0],
        "colsample_bytree": [0.8, 1.0],
    }

    keys = list(param_grid.keys())
    best = None
    results = []

    for values in itertools.product(*[param_grid[k] for k in keys]):
        params = dict(zip(keys, values))
        metrics = evaluate(params, X, y, w)
        result = {**params, **metrics}
        results.append(result)

        if best is None or metrics["f1_mean"] > best["f1_mean"]:
            best = result

        logger.info(f"Params {params} -> F1={metrics['f1_mean']:.4f} AUC={metrics['auc_mean']:.4f}")

    print()
    print("=" * 80)
    print("Best by F1:")
    print("=" * 80)
    print(json.dumps(best, indent=2, ensure_ascii=False))

    # Save all results
    out_path = Path("models/xgb_tuning_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"All results saved to {out_path}")


if __name__ == "__main__":
    main()
