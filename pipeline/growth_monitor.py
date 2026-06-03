"""Growth Score 核心模块：记录粉丝快照、计算真实 growth、定时转正。"""

import logging
from datetime import datetime, timezone

from db.connection import fetch_all, fetch_one, get_cursor
from config.settings import (
    GROWTH_SPAN_MIN_DAYS,
    GROWTH_ANOMALY_DROP_THRESHOLD,
    GROWTH_ANOMALY_MIN_FOLLOWERS,
    FOLLOWER_DROP_ALERT_THRESHOLD,
    FOLLOWER_DROP_MIN_FOLLOWERS,
    SEED_GROWTH_ALERT_THRESHOLD,
    SEED_GROWTH_MIN_FOLLOWERS,
)

logger = logging.getLogger(__name__)

_PLACEHOLDER = 50.0


def record_snapshot(
    creator_id: int,
    followers: int,
    following: int,
    tweets_count: int,
    source: str,
    is_seed: bool = False,
) -> None:
    """Write a follower snapshot. Idempotent on (creator_id, observed_at) day-level."""
    table = "seed_follower_snapshots" if is_seed else "creator_snapshots"
    with get_cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {table} (creator_id, observed_at, followers, following, tweets_count, source)
            VALUES (%s, DATE_TRUNC('day', NOW()), %s, %s, %s, %s)
            ON CONFLICT (creator_id, observed_at) DO UPDATE SET
                followers = EXCLUDED.followers,
                following = EXCLUDED.following,
                tweets_count = EXCLUDED.tweets_count,
                source = EXCLUDED.source
            """,
            (creator_id, followers, following, tweets_count, source),
        )
    # 对普通创作者检测粉丝量急剧下降
    if not is_seed:
        check_follower_drop_alert(creator_id, followers)
    # 对种子（SPS seed + BD interested）检测粉丝量大幅增长
    check_seed_growth_alert(creator_id, followers, is_seed)


def calc_growth(creator_id: int, is_seed: bool = False) -> tuple[float, bool]:
    """Return (growth_score, is_real)."""
    table = "seed_follower_snapshots" if is_seed else "creator_snapshots"
    rows = fetch_all(
        f"""
        SELECT observed_at, followers
        FROM {table}
        WHERE creator_id = %s
        ORDER BY observed_at ASC
        """,
        (creator_id,),
    )
    if not rows or len(rows) < 2:
        return (_PLACEHOLDER, False)

    earliest = rows[0]
    latest = rows[-1]
    days = (latest["observed_at"] - earliest["observed_at"]).days
    if days < GROWTH_SPAN_MIN_DAYS:
        return (_PLACEHOLDER, False)

    earliest_followers = max(earliest["followers"] or 0, 1)
    latest_followers = latest["followers"] or 0
    growth_rate = (latest_followers - earliest_followers) / earliest_followers

    # Anomaly 检测
    if (
        earliest["followers"]
        and earliest["followers"] > GROWTH_ANOMALY_MIN_FOLLOWERS
        and growth_rate < GROWTH_ANOMALY_DROP_THRESHOLD
    ):
        with get_cursor() as cur:
            cur.execute(
                f"""
                UPDATE {table}
                SET anomaly_type = 'sudden_drop',
                    anomaly_note = %s
                WHERE creator_id = %s AND observed_at = %s
                """,
                (
                    f"followers dropped {growth_rate:.2%} from {earliest['followers']} to {latest_followers}",
                    creator_id,
                    latest["observed_at"],
                ),
            )
        if len(rows) >= 3:
            normal = rows[-2]
            normal_followers = max(normal["followers"] or 0, 1)
            growth_rate = (latest_followers - normal_followers) / normal_followers
            days = (latest["observed_at"] - normal["observed_at"]).days
            if days < GROWTH_SPAN_MIN_DAYS:
                return (_PLACEHOLDER, False)
        else:
            return (_PLACEHOLDER, False)

    score = 50.0 + growth_rate * 100.0
    score = max(0.0, min(100.0, score))
    return (round(score, 2), True)


def refresh_growth_scores() -> dict:
    """Daily cron: find creators eligible for graduation and update."""
    from pipeline.sellability_model import predict_sellability
    from pipeline.sps_model import predict_sps

    checked = graduated = 0
    seed_graduated = False

    # 普通创作者
    eligible = fetch_all(
        """
        SELECT creator_id, MIN(observed_at) AS first_at, MAX(observed_at) AS last_at
        FROM creator_snapshots
        GROUP BY creator_id
        HAVING COUNT(*) >= 2 AND MAX(observed_at) - MIN(observed_at) >= INTERVAL '%s days'
        """,
        (GROWTH_SPAN_MIN_DAYS,),
    )

    for row in eligible:
        checked += 1
        cid = row["creator_id"]
        current = fetch_one(
            "SELECT growth_score FROM creator_features WHERE creator_id = %s",
            (cid,),
        )
        if current and current.get("growth_score") != _PLACEHOLDER:
            continue

        score, is_real = calc_growth(cid, is_seed=False)
        if not is_real:
            continue

        _update_growth_and_infer(cid, score, predict_sellability, predict_sps)
        graduated += 1

    # 种子用户
    seed_eligible = fetch_all(
        """
        SELECT creator_id, MIN(observed_at) AS first_at, MAX(observed_at) AS last_at
        FROM seed_follower_snapshots
        GROUP BY creator_id
        HAVING COUNT(*) >= 2 AND MAX(observed_at) - MIN(observed_at) >= INTERVAL '%s days'
        """,
        (GROWTH_SPAN_MIN_DAYS,),
    )

    for row in seed_eligible:
        checked += 1
        cid = row["creator_id"]
        current = fetch_one(
            "SELECT growth_score FROM creator_features WHERE creator_id = %s",
            (cid,),
        )
        if current and current.get("growth_score") != _PLACEHOLDER:
            continue

        score, is_real = calc_growth(cid, is_seed=True)
        if not is_real:
            continue

        _update_growth_and_infer(cid, score, predict_sellability, predict_sps)
        graduated += 1
        seed_graduated = True

    if seed_graduated:
        from pipeline.runner import train_models

        try:
            train_models()
            logger.info("Seed growth graduated → triggered full model retraining")
        except Exception:
            logger.exception("Model retraining after seed graduation failed")

    return {"checked": checked, "graduated": graduated}


def check_follower_drop_alert(creator_id: int, current_followers: int) -> bool:
    """Check if a creator's followers dropped sharply between the two most recent snapshots.

    Only applies to project-discovered, filtered creators:
    - bd_status IN ('rule_passed', 'ai_passed')
    - NOT is_seed
    - NOT bd_decision = 'interested'

    If triggered, inserts into follower_alerts and logs a warning.
    Returns True if alert was triggered.
    """
    creator = fetch_one(
        """SELECT is_seed, bd_status, bd_decision, username
           FROM creators WHERE id = %s""",
        (creator_id,),
    )
    if not creator:
        return False

    # 只针对"由项目发现的、通过了过滤的"创作者（非种子、非 BD interested）
    if bool(creator.get("is_seed")):
        return False
    if creator.get("bd_decision") == "interested":
        return False
    if creator.get("bd_status") not in ("rule_passed", "ai_passed"):
        return False

    # 查询上一条 snapshot（排除当天，避免与刚写入的行比较）
    prev = fetch_one(
        """SELECT followers
           FROM creator_snapshots
           WHERE creator_id = %s AND observed_at < DATE_TRUNC('day', NOW())
           ORDER BY observed_at DESC
           LIMIT 1""",
        (creator_id,),
    )
    if not prev or prev.get("followers") is None:
        return False

    prev_followers = prev["followers"]
    if prev_followers < FOLLOWER_DROP_MIN_FOLLOWERS:
        return False
    if prev_followers == 0:
        return False

    drop_rate = (current_followers - prev_followers) / prev_followers
    if drop_rate > FOLLOWER_DROP_ALERT_THRESHOLD:
        return False

    # 触发预警（幂等：ON CONFLICT DO NOTHING）
    note = f"followers dropped {drop_rate:.1%} from {prev_followers} to {current_followers}"
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO follower_alerts (creator_id, alerted_at, alert_note)
               VALUES (%s, NOW(), %s)
               ON CONFLICT (creator_id) DO NOTHING""",
            (creator_id, note),
        )

    logger.warning(
        "FOLLOWER_DROP_ALERT: creator_id=%s username=%s %s",
        creator_id,
        creator.get("username") or "unknown",
        note,
    )
    return True


def check_seed_growth_alert(creator_id: int, current_followers: int, is_seed: bool = False) -> bool:
    """Check if a seed or BD-interested creator's followers grew sharply.

    Targets:
    - is_seed = true (SPS model seeds from seed_file.csv)
    - bd_decision = 'interested' (Sellability model seeds)

    If triggered, inserts into seed_growth_alerts and logs an info message
    for follow-up / secondary collaboration opportunities.
    Returns True if alert was triggered.
    """
    creator = fetch_one(
        "SELECT is_seed, bd_decision, username FROM creators WHERE id = %s",
        (creator_id,),
    )
    if not creator:
        return False

    # 只针对种子（SPS seed + BD interested）
    if not (bool(creator.get("is_seed")) or creator.get("bd_decision") == "interested"):
        return False

    # 查询上一条 snapshot（根据 is_seed 选择表）
    table = "seed_follower_snapshots" if is_seed else "creator_snapshots"
    prev = fetch_one(
        f"""SELECT followers
            FROM {table}
            WHERE creator_id = %s AND observed_at < DATE_TRUNC('day', NOW())
            ORDER BY observed_at DESC
            LIMIT 1""",
        (creator_id,),
    )
    if not prev or prev.get("followers") is None:
        return False

    prev_followers = prev["followers"]
    if prev_followers < SEED_GROWTH_MIN_FOLLOWERS:
        return False
    if prev_followers == 0:
        return False

    growth_rate = (current_followers - prev_followers) / prev_followers
    if growth_rate < SEED_GROWTH_ALERT_THRESHOLD:
        return False

    # 触发提醒（已存在则更新，保持最新）
    note = f"followers grew {growth_rate:.1%} from {prev_followers} to {current_followers}"
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO seed_growth_alerts
                   (creator_id, alerted_at, alert_note, previous_followers, current_followers, growth_rate)
               VALUES (%s, NOW(), %s, %s, %s, %s)
               ON CONFLICT (creator_id) DO UPDATE SET
                   alerted_at = EXCLUDED.alerted_at,
                   alert_note = EXCLUDED.alert_note,
                   previous_followers = EXCLUDED.previous_followers,
                   current_followers = EXCLUDED.current_followers,
                   growth_rate = EXCLUDED.growth_rate""",
            (creator_id, note, prev_followers, current_followers, growth_rate),
        )

    logger.info(
        "SEED_GROWTH_ALERT: creator_id=%s username=%s %s",
        creator_id,
        creator.get("username") or "unknown",
        note,
    )
    return True


def _update_growth_and_infer(
    creator_id: int,
    score: float,
    predict_sellability,
    predict_sps,
) -> None:
    """Update growth_score in creator_features and rerun inference for one creator."""
    # 若已触发粉丝量急剧下降预警，不再投入模型推理
    alert_row = fetch_one(
        "SELECT alerted_at FROM follower_alerts WHERE creator_id = %s",
        (creator_id,),
    )
    if alert_row and alert_row.get("alerted_at"):
        logger.warning(
            "Skipping inference for creator_id=%s due to follower drop alert", creator_id
        )
        return

    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE creator_features
            SET growth_score = %s, calculated_at = NOW()
            WHERE creator_id = %s
            """,
            (score, creator_id),
        )

    features = fetch_one("SELECT * FROM creator_features WHERE creator_id = %s", (creator_id,))
    if not features:
        return

    sellability = predict_sellability(features)
    sps = predict_sps(features)

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO creator_scores (creator_id, sellability_score, sps_score, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (creator_id) DO UPDATE SET
                sellability_score = EXCLUDED.sellability_score,
                sps_score = EXCLUDED.sps_score,
                updated_at = NOW()
            """,
            (creator_id, sellability, sps),
        )


def is_growth_system_mature() -> bool:
    """Check if the system has been accumulating snapshots for at least 30 days.

    Uses the earliest observed_at across both snapshot tables as the system start date.
    This is resilient to redeployments because it's based on actual data, not config.
    """
    try:
        row = fetch_one(
            """
            SELECT MIN(observed_at) as start_date FROM (
                SELECT observed_at FROM creator_snapshots
                UNION ALL
                SELECT observed_at FROM seed_follower_snapshots
            ) t
            """
        )
    except Exception:
        # Table may not exist yet (e.g., during initial deployment/testing)
        return False
    if not row or not row["start_date"]:
        return False
    start = row["start_date"]
    if isinstance(start, str):
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - start).days >= GROWTH_SPAN_MIN_DAYS
