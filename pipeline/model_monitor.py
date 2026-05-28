"""模型监控 — 评估 Sellability 与 SPS 模型质量，写入 model_evaluations 表。

指标：
- Sellability（分类）：Recall, Precision, F2-Score, AUC
- SPS（排序+回归）：Precision@250, Spearman, Pearson, R², MAE, MAPE
"""

import json
import logging

import numpy as np
from scipy import stats as scipy_stats
from sklearn.metrics import (
    fbeta_score,
    mean_absolute_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)

from config.settings import (
    MODEL_META_PATH,
    SELLABILITY_MODEL_META_PATH,
    SELLABILITY_SCORE_THRESHOLD,
)
from db.connection import fetch_all, get_cursor

logger = logging.getLogger(__name__)

RECALL_THRESHOLD = 0.90
PRECISION_AT_250_THRESHOLD = 0.50


def _load_meta(meta_path: str) -> dict:
    """Load model metadata JSON; return empty dict on failure."""
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def evaluate_sellability() -> dict | None:
    """Evaluate Sellability classification model against BD review outcomes.

    Returns:
        Metrics dict or None if insufficient data.

    FIXME: 数据泄露 — 评价数据与训练数据高度重叠。
    Sellability 模型训练时使用 creators.bd_decision 作为标签，
    evaluate_sellability() 同样查询 bd_decision 进行评价。
    当前 BD 人工审核样本量不足（<20 条时会回退到种子/伪标签），
    无法拆分独立的训练/测试集。待样本量充足后（建议 >=200 条有标签数据），
    应改用时间窗口隔离（如仅使用模型训练后新增的 BD 反馈）或创作者 ID 隔离。
    """
    cls_rows = fetch_all(
        """SELECT cs.sellability_score, c.bd_decision
           FROM creator_scores cs
           JOIN creators c ON c.id = cs.creator_id
           WHERE c.bd_decision IN ('interested', 'rejected_unfit', 'rejected_not_creator')
             AND cs.sellability_score IS NOT NULL"""
    )

    if not cls_rows:
        logger.warning("Not enough BD-reviewed data for sellability evaluation")
        return None

    meta = _load_meta(SELLABILITY_MODEL_META_PATH)
    n_seeds = meta.get("n_samples", 0)

    y_true = np.array([1 if r["bd_decision"] == "interested" else 0 for r in cls_rows])
    sell_scores = np.array([float(r["sellability_score"]) for r in cls_rows])
    y_pred = (sell_scores >= SELLABILITY_SCORE_THRESHOLD).astype(int)

    recall = float(recall_score(y_true, y_pred, zero_division=0))
    precision = float(precision_score(y_true, y_pred, zero_division=0))
    f2 = float(fbeta_score(y_true, y_pred, beta=2, zero_division=0))

    auc = None
    if len(set(y_true.tolist())) > 1:
        auc = float(roc_auc_score(y_true, sell_scores / 100.0))

    n_interested = int(y_true.sum())
    n_rejected = int(len(y_true) - n_interested)

    metrics = {
        "model_name": "sellability",
        "model_version": f"{meta.get('model_type', '?')}_{meta.get('trained_at', '?')}",
        "n_seeds": n_seeds,
        "n_predictions": len(cls_rows),
        "n_bd_reviewed": len(cls_rows),
        "n_interested": n_interested,
        "n_rejected": n_rejected,
        "recall": round(recall, 4),
        "precision_score": round(precision, 4),
        "f2_score": round(f2, 4),
        "precision_at_250": None,
        "spearman_corr": None,
        "r2": None,
        "mae": None,
        "notes": json.dumps(
            {
                "sellability": {
                    "threshold": SELLABILITY_SCORE_THRESHOLD,
                    "auc": round(auc, 4) if auc is not None else None,
                    "n_rows": len(cls_rows),
                }
            },
            ensure_ascii=False,
        ),
    }

    _store_evaluation(metrics)
    _check_sellability_alerts(metrics)
    logger.info("Sellability evaluation: %s", metrics)
    return metrics


def evaluate_sps() -> dict | None:
    """Evaluate SPS ranking + regression model.

    Returns:
        Metrics dict or None if insufficient data.
    """
    reviewed = fetch_all(
        """SELECT cs.sps_score, c.bd_decision
           FROM creator_scores cs
           JOIN creators c ON c.id = cs.creator_id
           WHERE c.bd_decision IN ('interested', 'rejected_unfit', 'rejected_not_creator')
             AND cs.sps_score IS NOT NULL"""
    )

    if not reviewed:
        logger.warning("Not enough BD-reviewed data for SPS evaluation")
        return None

    meta = _load_meta(MODEL_META_PATH)
    n_seeds = meta.get("n_samples", 0)

    # --- Ranking metric: Precision@250 ---
    y_true_rank = np.array([1 if r["bd_decision"] == "interested" else 0 for r in reviewed])
    sps_scores = np.array([float(r["sps_score"]) for r in reviewed])

    sorted_indices = np.argsort(-sps_scores)
    top_k = min(250, len(reviewed))
    top_true = y_true_rank[sorted_indices[:top_k]]
    p_at_250 = float(top_true.sum()) / top_k if top_k > 0 else None

    # --- Regression metrics: predicted_sales vs actual GMV ---
    # FIXME: 回归评价目标不一致。
    # SPS 模型训练时以 creators.total_sales 为目标变量，
    # 而回归评价使用 sales_feedback.gmv 作为实际值。
    # 两者数据口径不同，导致 R²/MAE/Spearman 指标不能真实反映模型拟合效果。
    # 待数据口径统一后再修正。
    sales_rows = fetch_all(
        """SELECT cs.predicted_sales, SUM(sf.gmv) AS actual_sales
           FROM creator_scores cs
           JOIN sales_feedback sf ON sf.creator_id = cs.creator_id
           WHERE cs.predicted_sales IS NOT NULL
           GROUP BY cs.creator_id, cs.predicted_sales"""
    )

    spearman_corr = None
    r2 = None
    mae = None

    if len(sales_rows) >= 5:
        pred_sales = np.array([float(r["predicted_sales"]) for r in sales_rows])
        actual_sales = np.array([float(r["actual_sales"] or 0) for r in sales_rows])

        sp_val, _ = scipy_stats.spearmanr(pred_sales, actual_sales)
        spearman_corr = float(sp_val) if not np.isnan(sp_val) else None

        r2 = float(r2_score(actual_sales, pred_sales))
        mae = float(mean_absolute_error(actual_sales, pred_sales))

    n_interested = int(y_true_rank.sum())
    n_rejected = int(len(y_true_rank) - n_interested)

    metrics = {
        "model_name": "sps",
        "model_version": f"{meta.get('model_type', '?')}_{meta.get('trained_at', '?')}",
        "n_seeds": n_seeds,
        "n_predictions": len(reviewed),
        "n_bd_reviewed": len(reviewed),
        "n_interested": n_interested,
        "n_rejected": n_rejected,
        "recall": None,
        "precision_score": None,
        "f2_score": None,
        "precision_at_250": round(p_at_250, 4) if p_at_250 is not None else None,
        "spearman_corr": round(spearman_corr, 4) if spearman_corr is not None else None,
        "r2": round(r2, 4) if r2 is not None else None,
        "mae": round(mae, 4) if mae is not None else None,
        "notes": json.dumps(
            {
                "sps": {
                    "sales_regression_n_rows": len(sales_rows),
                }
            },
            ensure_ascii=False,
        ),
    }

    _store_evaluation(metrics)
    _check_sps_alerts(metrics)
    logger.info("SPS evaluation: %s", metrics)
    return metrics


def evaluate_model() -> list[dict]:
    """Evaluate both models and store results independently.

    Returns:
        List of metrics dicts (one per successfully evaluated model).
    """
    results: list[dict] = []
    sell_result = evaluate_sellability()
    if sell_result:
        results.append(sell_result)
    sps_result = evaluate_sps()
    if sps_result:
        results.append(sps_result)
    return results


def _store_evaluation(metrics: dict) -> None:
    """Insert evaluation results into model_evaluations table."""
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO model_evaluations
                   (model_name, model_version, n_seeds, n_predictions, n_bd_reviewed,
                    n_interested, n_rejected,
                    recall, precision_score, f2_score, precision_at_250,
                    spearman_corr, r2, mae, notes)
               VALUES (%(model_name)s, %(model_version)s, %(n_seeds)s, %(n_predictions)s, %(n_bd_reviewed)s,
                       %(n_interested)s, %(n_rejected)s,
                       %(recall)s, %(precision_score)s, %(f2_score)s, %(precision_at_250)s,
                       %(spearman_corr)s, %(r2)s, %(mae)s, %(notes)s)""",
            metrics,
        )


def _check_sellability_alerts(metrics: dict) -> None:
    """Log warnings if sellability metrics fall below thresholds."""
    if metrics.get("recall") is not None and metrics["recall"] < RECALL_THRESHOLD:
        logger.warning(
            "ALERT: Sellability Recall %.2f%% < target %.0f%%",
            metrics["recall"] * 100,
            RECALL_THRESHOLD * 100,
        )
    try:
        notes = json.loads(metrics.get("notes") or "{}")
        auc = notes.get("sellability", {}).get("auc")
        if auc is not None and auc < 0.65:
            logger.warning("ALERT: Sellability AUC %.2f < target 0.65", auc)
    except Exception:
        pass


def _check_sps_alerts(metrics: dict) -> None:
    """Log warnings if SPS metrics fall below thresholds."""
    if (
        metrics.get("precision_at_250") is not None
        and metrics["precision_at_250"] < PRECISION_AT_250_THRESHOLD
    ):
        logger.warning(
            "ALERT: SPS Precision@250 %.2f%% < target %.0f%%",
            metrics["precision_at_250"] * 100,
            PRECISION_AT_250_THRESHOLD * 100,
        )
