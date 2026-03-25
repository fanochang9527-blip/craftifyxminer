"""SPS 评分 + 中心度分层。

SPS = sum(weight_i * score_i) for 10 dimensions，权重矩阵按 creator_type 从 weights.yaml 加载。
中心度: seed_connections -> Hub(>=5) / Connector(2-4) / Peripheral(0-1)。
Contact Probability: 初版 SPS*0.8 + Monetization*0.2。
"""

import logging

import yaml

from config.settings import WEIGHTS_PATH
from db.connection import fetch_all, fetch_one, get_cursor
from pipeline.feature_engine import circle_influence_score_from_seed_connections

logger = logging.getLogger(__name__)

_weights: dict | None = None

FEATURE_KEYS = [
    "audience_score",
    "engagement_score",
    "virality_score",
    "posting_score",
    "monetization_score",
    "growth_score",
    "circle_influence_score",
    "character_consistency",
    "community_score",
    "data_confidence",
]

WEIGHT_KEYS = [
    "audience",
    "engagement",
    "virality",
    "posting",
    "monetization",
    "growth",
    "circle_influence_score",
    "character_consistency",
    "community",
    "data_confidence",
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
    """Calculate SPS as weighted sum of 10 feature dimensions."""
    w = get_weights_for_type(creator_type)
    total = 0.0
    for fk, wk in zip(FEATURE_KEYS, WEIGHT_KEYS):
        score = float(features.get(fk, 0) or 0)
        weight = float(w.get(wk, 0) or 0)
        total += score * weight
    return round(total, 2)


def calc_contact_probability(sps: float, monetization: float) -> float:
    """Simplified contact probability: SPS*0.8 + Monetization*0.2, normalized to 0-1."""
    raw = sps * 0.8 + monetization * 0.2
    return round(min(raw / 100.0, 1.0), 4)


def score_creator(creator_id: int) -> dict | None:
    """Compute SPS, centrality, and contact probability for one creator."""
    features = fetch_one(
        "SELECT * FROM creator_features WHERE creator_id = %s",
        (creator_id,),
    )
    if not features:
        return None

    # Determine creator type from scores table or features
    type_row = fetch_one(
        "SELECT creator_type FROM creator_scores WHERE creator_id = %s",
        (creator_id,),
    )
    creator_type = (type_row or {}).get("creator_type") or "content_creator"

    # Seed connections for centrality
    seed_row = fetch_one(
        """SELECT COUNT(*) AS cnt FROM creator_graph cg
           JOIN creators c ON c.id = cg.creator_id
           WHERE cg.connected_creator_id = %s AND c.is_seed = true""",
        (creator_id,),
    )
    seed_connections = int(seed_row["cnt"]) if seed_row else 0

    sps = calc_sps(dict(features), creator_type)
    centrality = classify_centrality(seed_connections)
    contact_prob = calc_contact_probability(sps, float(features.get("monetization_score") or 0))

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO creator_scores
                   (creator_id, creator_type, sps_score, confidence,
                    centrality_tier, seed_connections,
                    contact_probability, predicted_response_rate)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (creator_id) DO UPDATE SET
                   sps_score = EXCLUDED.sps_score,
                   centrality_tier = EXCLUDED.centrality_tier,
                   seed_connections = EXCLUDED.seed_connections,
                   contact_probability = EXCLUDED.contact_probability,
                   updated_at = NOW()""",
            (
                creator_id,
                creator_type,
                sps,
                features.get("data_confidence", 0),
                centrality,
                seed_connections,
                contact_prob,
                contact_prob,
            ),
        )

    return {
        "creator_id": creator_id,
        "sps_score": sps,
        "centrality_tier": centrality,
        "seed_connections": seed_connections,
        "contact_probability": contact_prob,
    }


def score_all_pending() -> int:
    """Score all creators that have features but no SPS score yet."""
    rows = fetch_all(
        """SELECT cf.creator_id FROM creator_features cf
           LEFT JOIN creator_scores cs ON cs.creator_id = cf.creator_id
           WHERE cs.id IS NULL"""
    )
    count = 0
    for row in rows:
        result = score_creator(row["creator_id"])
        if result:
            count += 1
    logger.info("Scored %d creators", count)
    return count
