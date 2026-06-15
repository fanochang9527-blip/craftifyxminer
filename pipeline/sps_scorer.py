"""SPS 评分 + 中心度分层。

双模型口径：
- sellability_score/is_sellable: 是否建议联系（Model A）
- sps_score: 预测销量评分（Model B）

优先使用 ML 模型；模型不可用时 fallback 到 weighted-sum。
中心度: seed_connections -> Hub(>=5) / Connector(2-4) / Peripheral(0-1)。
Contact Probability: 初版 SPS*0.8 + Monetization*0.2。
"""

import logging

import yaml

from config.settings import SELLABILITY_SCORE_THRESHOLD, SPS_SALES_NORMALIZER
from config.settings import WEIGHTS_PATH
from db.connection import fetch_all, fetch_one, get_cursor

logger = logging.getLogger(__name__)

_weights: dict | None = None

FEATURE_KEYS = [
    "audience_score",
    "engagement_score",
    "virality_score",
    "posting_score",
    "monetization_score",
    # FIXME: 临时停用 growth_score，待历史粉丝快照积累足够后重新启用
    # "growth_score",
    # "character_consistency",
    "community_score",
    "audience_segment_score",
]

WEIGHT_KEYS = [
    "audience",
    "engagement",
    "virality",
    "posting",
    "monetization",
    # FIXME: 临时停用 growth 权重，待历史粉丝快照积累足够后重新启用
    # "growth",
    # "character_consistency",
    "community",
    "audience_segment",
]


def _load_weights() -> dict:
    global _weights
    if _weights is None:
        with open(WEIGHTS_PATH, encoding="utf-8") as f:
            _weights = yaml.safe_load(f)
    return _weights


def get_weights_for_type(creator_type: str) -> dict:
    """Return the weight vector for a creator type, defaulting to content_creator."""
    weights = _load_weights()
    return weights.get(creator_type, weights.get("content_creator", {}))


def classify_centrality(seed_connections: int) -> str:
    if seed_connections >= 5:
        return "Hub"
    if seed_connections >= 2:
        return "Connector"
    return "Peripheral"


def calc_sps(features: dict, creator_type: str) -> float:
    """Calculate SPS score — weighted-sum fallback used by Model B."""
    try:
        from pipeline.sps_model import predict_sps
        features_with_type = {**features, "creator_type": creator_type}
        ml_score = predict_sps(features_with_type)
        if ml_score is not None:
            return ml_score
    except Exception:
        logger.debug("ML prediction failed — falling back to weighted sum")

    w = get_weights_for_type(creator_type)
    total = 0.0
    for fk, wk in zip(FEATURE_KEYS, WEIGHT_KEYS):
        score = float(features.get(fk, 0) or 0)
        weight = float(w.get(wk, 0) or 0)
        total += score * weight
    return round(min(total, 100.0), 2)


def calc_sellability(features: dict, creator_type: str) -> float:
    """Calculate sellability score (0-100) — Model A first, heuristic fallback."""
    try:
        from pipeline.sellability_model import predict_sellability

        score = predict_sellability({**features, "creator_type": creator_type})
        if score is not None:
            return float(score)
    except Exception:
        logger.debug("Sellability model prediction failed — using heuristic fallback")

    # 冷启动启发式：偏重变现/互动/社区
    monetization = float(features.get("monetization_score") or 0)
    engagement = float(features.get("engagement_score") or 0)
    community = float(features.get("community_score") or 0)
    heuristic = monetization * 0.45 + engagement * 0.30 + community * 0.25
    return round(max(0.0, min(100.0, heuristic)), 2)


def calc_predicted_sales(features: dict, creator_type: str) -> tuple[float, float]:
    """Return (predicted_sales, sps_score)."""
    try:
        from pipeline.sps_model import predict_sales, sales_to_sps

        sales = predict_sales({**features, "creator_type": creator_type})
        if sales is not None:
            return float(sales), float(sales_to_sps(sales))
    except Exception:
        logger.debug("Sales model prediction failed — using weighted fallback")

    # fallback：用旧 weighted SPS 估算销量
    sps = calc_sps(features, creator_type)
    sales = max(0.0, float(sps) * SPS_SALES_NORMALIZER)
    return round(sales, 2), round(float(sps), 2)


def calc_contact_probability(sps: float, monetization: float) -> float:
    """Simplified contact probability: SPS*0.8 + Monetization*0.2, normalized to 0-1."""
    raw = sps * 0.8 + monetization * 0.2
    return round(min(raw / 100.0, 1.0), 4)


def score_creator(creator_id: int) -> dict | None:
    """Compute SPS, centrality, and contact probability for one creator."""
    # 若已触发粉丝量急剧下降预警，跳过评分
    alert_row = fetch_one(
        "SELECT alerted_at FROM follower_alerts WHERE creator_id = %s",
        (creator_id,),
    )
    if alert_row and alert_row.get("alerted_at"):
        logger.warning(
            "Skipping score for creator_id=%s due to follower drop alert", creator_id
        )
        return None

    features = fetch_one(
        "SELECT * FROM creator_features WHERE creator_id = %s",
        (creator_id,),
    )
    if not features:
        return None

    type_row = fetch_one(
        """SELECT COALESCE(creator_type_manual, creator_type_auto, 'unknown') AS creator_type
           FROM creators WHERE id = %s""",
        (creator_id,),
    )
    creator_type = (type_row or {}).get("creator_type") or "content_creator"

    seed_row = fetch_one(
        """SELECT COUNT(*) AS cnt FROM creator_graph cg
           JOIN creators c ON c.id = cg.creator_id
           WHERE cg.connected_creator_id = %s AND c.is_seed = true""",
        (creator_id,),
    )
    seed_connections = int(seed_row["cnt"]) if seed_row else 0

    sellability_score = calc_sellability(dict(features), creator_type)
    is_sellable = sellability_score >= SELLABILITY_SCORE_THRESHOLD
    # 不再把非 sellable 直接归零，保留预测销量与 SPS，供工作台解释与复核。
    predicted_sales, sps = calc_predicted_sales(dict(features), creator_type)
    centrality = classify_centrality(seed_connections)
    contact_prob = calc_contact_probability(sps, float(features.get("monetization_score") or 0))

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO creator_scores
                   (creator_id, creator_type, sellability_score, is_sellable, predicted_sales,
                    sps_score, confidence,
                    centrality_tier, seed_connections,
                    contact_probability, predicted_response_rate)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (creator_id) DO UPDATE SET
                   creator_type = EXCLUDED.creator_type,
                   sellability_score = EXCLUDED.sellability_score,
                   is_sellable = EXCLUDED.is_sellable,
                   predicted_sales = EXCLUDED.predicted_sales,
                   sps_score = EXCLUDED.sps_score,
                   centrality_tier = EXCLUDED.centrality_tier,
                   seed_connections = EXCLUDED.seed_connections,
                   contact_probability = EXCLUDED.contact_probability,
                   updated_at = NOW()""",
            (
                creator_id,
                creator_type,
                sellability_score,
                is_sellable,
                predicted_sales,
                sps,
                0.0,
                centrality,
                seed_connections,
                contact_prob,
                contact_prob,
            ),
        )

    return {
        "creator_id": creator_id,
        "sellability_score": sellability_score,
        "is_sellable": is_sellable,
        "predicted_sales": predicted_sales,
        "sps_score": sps,
        "centrality_tier": centrality,
        "seed_connections": seed_connections,
        "contact_probability": contact_prob,
    }


def score_all_pending() -> int:
    """Score all creators that have features but no SPS score yet."""
    # FIXME: 临时停用 growth_score 成熟度过滤，待历史粉丝快照积累足够后重新启用
    # from pipeline.growth_monitor import is_growth_system_mature

    # maturity_filter = ""
    # if is_growth_system_mature():
    #     maturity_filter = "AND cf.growth_score IS DISTINCT FROM 50.0"
    maturity_filter = ""

    rows = fetch_all(
        f"""SELECT cf.creator_id FROM creator_features cf
           LEFT JOIN creator_scores cs ON cs.creator_id = cf.creator_id
           LEFT JOIN follower_alerts fa ON fa.creator_id = cf.creator_id
           WHERE fa.creator_id IS NULL
             AND (cs.id IS NULL
              OR cs.sellability_score IS NULL
              OR cs.predicted_sales IS NULL)
             {maturity_filter}"""
    )
    count = 0
    for row in rows:
        result = score_creator(row["creator_id"])
        if result:
            count += 1
    logger.info("Scored %d creators", count)
    return count
