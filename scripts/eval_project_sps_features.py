"""项目级销量预测新特征方案离线 CV 评估。

由于旧方案涉及的列（creator_avg_daily_posts_30d、creator_reply_engagement_rate、
creator_market_tier_high/mid/low、creator_content_*）已随迁移脚本删除，
旧模型文件也处于 .gitignore 中无历史备份，因此本脚本仅对新方案（10 维枚举编码特征）
做 5-Fold CV 评估，输出 log/原始销量空间的多项指标。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from xgboost import XGBRegressor

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.connection import fetch_all
from pipeline.project_sps_model import (
    CREATOR_ENUM_FEATURES,
    CREATOR_FEATURES,
    PROJECT_ENUM_FEATURES,
    PROJECT_NUMERIC_FEATURES,
    _build_feature_vector,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def load_data() -> list[dict]:
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
        raise ValueError("No project data found")
    return rows


def evaluate(name: str, X: np.ndarray, y_log: np.ndarray, raw_y: np.ndarray, n_splits: int = 5, model_type: str = "ridge") -> dict:
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    preds_log = np.zeros_like(y_log)

    for train_idx, val_idx in kf.split(X):
        if model_type == "xgboost":
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
        else:
            model = Ridge(alpha=1.0)
        model.fit(X[train_idx], y_log[train_idx])
        preds_log[val_idx] = model.predict(X[val_idx])

    preds_raw = np.expm1(preds_log)

    mae_log = float(np.mean(np.abs(preds_log - y_log)))
    rmse_log = float(np.sqrt(np.mean((preds_log - y_log) ** 2)))
    spearman = float(spearmanr(preds_log, y_log)[0])

    mae_raw = float(np.mean(np.abs(preds_raw - raw_y)))
    medae_raw = float(np.median(np.abs(preds_raw - raw_y)))
    mape_raw = float(np.mean(np.abs((preds_raw - raw_y) / np.maximum(raw_y, 1e-6))) * 100)

    # 简单命中率：预测值在真实值 ±50% 范围内的比例
    within_50_pct = float(np.mean(np.abs(preds_raw - raw_y) <= 0.5 * raw_y) * 100)

    return {
        "name": name,
        "n_samples": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "mae_log": round(mae_log, 4),
        "rmse_log": round(rmse_log, 4),
        "spearman": round(spearman, 4),
        "mae_raw": round(mae_raw, 2),
        "medae_raw": round(medae_raw, 2),
        "mape_raw": round(mape_raw, 2),
        "within_50_pct": round(within_50_pct, 2),
    }


def main() -> None:
    rows = load_data()
    raw_y = np.array([float(r["order_quantity"]) for r in rows])
    y_log = np.log1p(raw_y)
    X = np.array([_build_feature_vector(r) for r in rows])

    ridge_result = evaluate("新方案 枚举编码 + Ridge (10维)", X, y_log, raw_y, model_type="ridge")
    xgb_result = evaluate("新方案 枚举编码 + XGBoost (10维)", X, y_log, raw_y, model_type="xgboost")

    print("\n" + "=" * 70)
    print("项目级销量预测新特征方案离线评估（5-Fold CV）")
    print("=" * 70)
    for r in (ridge_result, xgb_result):
        print(f"\n{r['name']}")
        print(f"  样本数: {r['n_samples']}  特征数: {r['n_features']}")
        print(f"  log空间  MAE: {r['mae_log']}  |  RMSE: {r['rmse_log']}  |  Spearman: {r['spearman']}")
        print(f"  原始销量 MAE: {r['mae_raw']}  |  MedAE: {r['medae_raw']}  |  MAPE: {r['mape_raw']}%")
        print(f"  预测值落在真实值 ±50% 范围内比例: {r['within_50_pct']}%")

    print("\n" + "-" * 70)
    print("说明：旧方案特征列已随迁移脚本删除，旧模型文件在 .gitignore 中无历史备份，")
    print("      因此无法直接做新旧方案 A/B 对比。本表对比了同一新特征在 Ridge 与 XGBoost 下的表现。")
    if xgb_result["spearman"] > ridge_result["spearman"]:
        print(f"      XGBoost 在当前枚举编码特征上的 Spearman ({xgb_result['spearman']}) 优于 Ridge ({ridge_result['spearman']})，")
        print("      说明枚举编码在树模型下更能发挥互斥关系的优势。")


if __name__ == "__main__":
    main()
