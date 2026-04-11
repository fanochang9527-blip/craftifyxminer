"""模型监控 — 评估 SPS 预测模型质量，写入 model_evaluations 表。

指标：Recall, Precision, F2-Score, Precision@250, Spearman 相关系数, R², MAE
"""

import json
import logging

import numpy as np
from scipy import stats as scipy_stats
from sklearn.metrics import (
    roc_auc_score,
    fbeta_score,
    mean_absolute_error,
    precision_score,
    r2_score,
    recall_score,
)

from config.settings import MODEL_META_PATH, SELLABILITY_SCORE_THRESHOLD
from db.connection import fetch_all, get_cursor

logger = logging.getLogger(__name__)

RECALL_THRESHOLD = 0.90
PRECISION_AT_250_THRESHOLD = 0.50


def evaluate_model(sps_threshold: float = 50.0) -> dict:
    """Evaluate dual-model outputs against BD review outcomes.

    Model A（sellability）:
      - y=true from bd_decision (interested=1, rejected*=0)
      - score=sellability_score

    Model B（sales/SPS）:
      - 排序指标沿用：top-K 的 interested 命中率
      - 回归指标：predicted_sales vs feedback.gmv（如有）

    Args:
        sps_threshold: SPS score above which we predict "positive".

    Returns:
        Dict of evaluation metrics.
    """
    reviewed = fetch_all(
        """SELECT cs.sps_score, c.bd_decision
           FROM creator_scores cs
           JOIN creators c ON c.id = cs.creator_id
           WHERE c.bd_decision IN ('interested', 'rejected_unfit', 'rejected_not_creator')
             AND cs.sps_score IS NOT NULL"""
    )

    cls_rows = fetch_all(
        """SELECT cs.sellability_score, c.bd_decision
           FROM creator_scores cs
           JOIN creators c ON c.id = cs.creator_id
           WHERE c.bd_decision IN ('interested', 'rejected_unfit', 'rejected_not_creator')
             AND cs.sellability_score IS NOT NULL"""
    )

    if len(reviewed) < 10 and len(cls_rows) < 10:
        n_rows = max(len(reviewed), len(cls_rows))
        logger.warning("Not enough BD-reviewed data for evaluation (%d rows)", n_rows)
        return {"error": "insufficient_data", "n_rows": n_rows}

    # --- Model A: sellability classification ---
    y_true_cls = np.array([1 if r["bd_decision"] == "interested" else 0 for r in cls_rows]) if cls_rows else np.array([])
    sell_scores = np.array([float(r["sellability_score"]) for r in cls_rows]) if cls_rows else np.array([])
    y_pred_cls = (sell_scores >= SELLABILITY_SCORE_THRESHOLD).astype(int) if cls_rows else np.array([])

    recall = float(recall_score(y_true_cls, y_pred_cls, zero_division=0)) if cls_rows else 0.0
    precision = float(precision_score(y_true_cls, y_pred_cls, zero_division=0)) if cls_rows else 0.0
    f2 = float(fbeta_score(y_true_cls, y_pred_cls, beta=2, zero_division=0)) if cls_rows else 0.0
    auc = 0.0
    if cls_rows and len(set(y_true_cls.tolist())) > 1:
        auc = float(roc_auc_score(y_true_cls, sell_scores / 100.0))

    # --- Model B: ranking on SPS ---
    y_true_rank = np.array([1 if r["bd_decision"] == "interested" else 0 for r in reviewed]) if reviewed else np.array([])
    sps_scores = np.array([float(r["sps_score"]) for r in reviewed]) if reviewed else np.array([])

    # Precision@250: among top-250 by SPS, what fraction is "interested"?
    sorted_indices = np.argsort(-sps_scores) if reviewed else np.array([])
    top_k = min(250, len(reviewed))
    top_true = y_true_rank[sorted_indices[:top_k]] if reviewed else np.array([])
    p_at_250 = float(top_true.sum()) / top_k if top_k > 0 else 0.0

    # --- Model B regression: predicted_sales vs actual GMV ---
    sales_rows = fetch_all(
        """SELECT cs.predicted_sales, SUM(sf.gmv) AS actual_sales
           FROM creator_scores cs
           JOIN sales_feedback sf ON sf.creator_id = cs.creator_id
           WHERE cs.predicted_sales IS NOT NULL
           GROUP BY cs.creator_id, cs.predicted_sales"""
    )
    if len(sales_rows) >= 5:
        pred_sales = np.array([float(r["predicted_sales"]) for r in sales_rows])
        actual_sales = np.array([float(r["actual_sales"] or 0) for r in sales_rows])
        spearman_corr, _ = scipy_stats.spearmanr(pred_sales, actual_sales)
        spearman_corr = float(spearman_corr) if not np.isnan(spearman_corr) else 0.0
        r2 = float(r2_score(actual_sales, pred_sales))
        mae = float(mean_absolute_error(actual_sales, pred_sales))
    else:
        spearman_corr = 0.0
        r2 = 0.0
        mae = 0.0

    n_interested = int(y_true_rank.sum()) if reviewed else 0
    n_rejected = int(len(y_true_rank) - n_interested) if reviewed else 0

    model_version = "unknown"
    try:
        with open(MODEL_META_PATH, encoding="utf-8") as f:
            meta = json.load(f)
            model_version = f"{meta.get('model_type', '?')}_{meta.get('trained_at', '?')}"
    except Exception:
        pass

    metrics = {
        "model_version": model_version,
        "n_seeds": 0,
        "n_predictions": len(reviewed),
        "n_bd_reviewed": len(reviewed),
        "n_interested": n_interested,
        "n_rejected": n_rejected,
        "recall": round(recall, 4),
        "precision_score": round(precision, 4),
        "f2_score": round(f2, 4),
        "precision_at_250": round(p_at_250, 4),
        "spearman_corr": round(spearman_corr, 4),
        "r2": round(r2, 4),
        "mae": round(mae, 4),
        "sps_threshold": sps_threshold,
        "notes": json.dumps(
            {
                "sellability": {
                    "threshold": SELLABILITY_SCORE_THRESHOLD,
                    "auc": round(auc, 4),
                    "n_rows": len(cls_rows),
                },
                "sales_regression": {
                    "n_rows": len(sales_rows),
                },
            },
            ensure_ascii=False,
        ),
    }

    _store_evaluation(metrics)
    _check_alerts(metrics)

    logger.info("Model evaluation: %s", metrics)
    return metrics


def _store_evaluation(metrics: dict) -> None:
    """Insert evaluation results into model_evaluations table."""
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO model_evaluations
                   (model_version, n_seeds, n_predictions, n_bd_reviewed,
                    n_interested, n_rejected,
                    recall, precision_score, f2_score, precision_at_250,
                    spearman_corr, r2, mae, sps_threshold, notes)
               VALUES (%(model_version)s, %(n_seeds)s, %(n_predictions)s, %(n_bd_reviewed)s,
                       %(n_interested)s, %(n_rejected)s,
                       %(recall)s, %(precision_score)s, %(f2_score)s, %(precision_at_250)s,
                       %(spearman_corr)s, %(r2)s, %(mae)s, %(sps_threshold)s, %(notes)s)""",
            metrics,
        )


def _check_alerts(metrics: dict) -> None:
    """Log warnings if key metrics fall below thresholds."""
    if metrics.get("recall", 1.0) < RECALL_THRESHOLD:
        logger.warning(
            "ALERT: Recall %.2f%% < target %.0f%%",
            metrics["recall"] * 100, RECALL_THRESHOLD * 100,
        )
    if metrics.get("precision_at_250", 1.0) < PRECISION_AT_250_THRESHOLD:
        logger.warning(
            "ALERT: Precision@250 %.2f%% < target %.0f%%",
            metrics["precision_at_250"] * 100, PRECISION_AT_250_THRESHOLD * 100,
        )
    try:
        notes = json.loads(metrics.get("notes") or "{}")
        auc = float(((notes.get("sellability") or {}).get("auc")) or 0.0)
        if auc and auc < 0.65:
            logger.warning("ALERT: Sellability AUC %.2f < target 0.65", auc)
    except Exception:
        pass
