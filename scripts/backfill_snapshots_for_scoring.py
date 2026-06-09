"""补算粉丝快照 — 为通过 AI 筛选且将要进入模型推理的创作者采集历史粉丝快照。

现有 follower_refresh 仅覆盖 is_seed=true 或 bd_decision='interested' 的创作者。
本脚本面向：
  - bd_status IN ('rule_passed', 'ai_passed')
  - 内容风格分析通过：非写实风格 (is_realistic=false) 且具备角色一致性 (has_fixed_ip=true)
  - 已有 creator_features（即将/等待进入模型推理）
  - 但 creator_scores 不完整（sellability_score 或 predicted_sales 为 NULL）
  - 非种子、非 BD interested（未被 follower_refresh 覆盖）

采集后写入 creator_snapshots，为 growth_score 转正提供第二个时间点，
使这些创作者能够尽快完成模型推理。

使用方式:
    python scripts/backfill_snapshots_for_scoring.py
    python scripts/backfill_snapshots_for_scoring.py --batch-size 50
    python scripts/backfill_snapshots_for_scoring.py --dry-run
    python scripts/backfill_snapshots_for_scoring.py --duration-days 30

运行模式:
    脚本启动后会进入循环，每 3 天自动执行一次快照补采，
    持续运行 --duration-days 天后自动退出。
    期间可通过 Ctrl+C 或 SIGTERM 优雅终止。
"""

import argparse
import logging
import signal
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from apify_client import ApifyClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    APIFY_API_TOKEN,
    APIFY_BUDGET_HARD_LIMIT,
    APIFY_CONFIG_PATH,
    DAILY_APIFY_BUDGET_USD,
    FOLLOWER_REFRESH_BATCH_SIZE,
    FOLLOWER_REFRESH_INTERVAL_DAYS,
)
from db.connection import fetch_all, fetch_one, get_cursor, upsert_cost
from pipeline.growth_monitor import record_snapshot

logger = logging.getLogger(__name__)


def _get_candidates(limit: int = FOLLOWER_REFRESH_BATCH_SIZE) -> list[dict]:
    """Fetch AI-filtered creators that are pending scoring but lack follower refresh coverage.

    筛选条件：
      - 已通过 AI 筛选 (bd_status = 'rule_passed' 或 'ai_passed')
      - 内容风格分析通过：非写实风格且具备角色一致性
        (creator_content_analysis.status='analyzed',
         is_realistic=false, has_fixed_ip=true)
      - 已有 creator_features（说明已完成 Step 6 特征计算）
      - growth_is_real = false（growth_score 尚未转正，快照跨度不足 30 天）
      - creator_scores 不完整（sellability_score 或 predicted_sales 为 NULL，等待模型推理）
      - 非种子、非 BD interested（未被 follower_refresh 覆盖）
      - 无粉丝量急剧下降预警（follower_alerts）
      - 超过 3 天未刷新过粉丝数据，或从未刷新过
    """
    return fetch_all(
        """
        SELECT c.id, c.username, c.is_seed
        FROM creators c
        JOIN creator_features cf ON cf.creator_id = c.id
        LEFT JOIN creator_scores cs ON cs.creator_id = c.id
        LEFT JOIN follower_alerts fa ON fa.creator_id = c.id
        JOIN creator_content_analysis cca ON cca.creator_id = c.id
        WHERE c.bd_status IN ('rule_passed', 'ai_passed')
          AND cca.status = 'analyzed'
          AND cca.is_realistic = false
          AND cca.has_fixed_ip = true
          AND c.is_seed = false
          AND c.bd_decision IS DISTINCT FROM 'interested'
          AND fa.creator_id IS NULL
          AND (cf.growth_is_real = false OR cf.growth_is_real IS NULL)
          AND (cs.id IS NULL
               OR cs.sellability_score IS NULL
               OR cs.predicted_sales IS NULL)
          AND (c.last_follower_refresh_at IS NULL
               OR c.last_follower_refresh_at < NOW() - INTERVAL '%s days')
        ORDER BY c.last_follower_refresh_at ASC NULLS FIRST, c.first_seen_at ASC
        LIMIT %s
        """,
        (FOLLOWER_REFRESH_INTERVAL_DAYS, limit),
    )


def _check_budget() -> bool:
    """Check daily Apify budget."""
    row = fetch_one(
        "SELECT COALESCE(SUM(apify_cost_usd), 0) AS today FROM cost_tracking WHERE date = CURRENT_DATE"
    )
    today = float(row["today"]) if row else 0.0
    if today >= DAILY_APIFY_BUDGET_USD:
        if APIFY_BUDGET_HARD_LIMIT:
            logger.warning(
                "Daily Apify budget exceeded ($%.2f) — blocking snapshot backfill", today
            )
            return False
        logger.warning(
            "Daily Apify budget exceeded ($%.2f) — continuing anyway", today
        )
    return True


def _store_results(items: list[dict]) -> dict:
    """Parse following_actor results and update creators + snapshots."""
    updated = 0
    for item in items:
        author = item.get("author") or item
        username = (
            (author.get("userName") or author.get("username") or "").lstrip("@").lower()
            or (item.get("userName") or item.get("username") or "").lstrip("@").lower()
        )
        if not username:
            continue

        followers = author.get("followers") or author.get("followersCount") or 0
        following = author.get("following") or author.get("friendsCount") or 0
        tweets_count = author.get("statusesCount") or author.get("tweetsCount") or 0

        with get_cursor() as cur:
            cur.execute(
                """UPDATE creators SET
                       followers = COALESCE(%s, followers),
                       following = COALESCE(%s, following),
                       tweets_count = COALESCE(%s, tweets_count),
                       last_follower_refresh_at = NOW()
                   WHERE username = %s
                   RETURNING id, is_seed""",
                (followers, following, tweets_count, username),
            )
            row = cur.fetchone()
            if not row:
                continue
            creator_id = row["id"]
            is_seed = row.get("is_seed")
            updated += 1

        # Snapshot 写入（独立事务，幂等兜底）
        record_snapshot(
            creator_id=creator_id,
            followers=followers,
            following=following,
            tweets_count=tweets_count,
            source="backfill_for_scoring",
            is_seed=bool(is_seed),
        )

    return {"updated": updated}


def run_backfill(limit: int = FOLLOWER_REFRESH_BATCH_SIZE, dry_run: bool = False) -> dict:
    """Trigger follower snapshot backfill for AI-filtered creators pending scoring.

    Returns: {"candidates": int, "run_id": str|None, "budget_ok": bool, "updated": int}
    """
    if not _check_budget():
        return {"candidates": 0, "run_id": None, "budget_ok": False, "updated": 0}

    candidates = _get_candidates(limit)
    if not candidates:
        logger.info("No AI-filtered creators pending snapshot backfill for scoring")
        return {"candidates": 0, "run_id": None, "budget_ok": True, "updated": 0}

    handles = [c["username"] for c in candidates]
    logger.info(
        "Backfilling snapshots for %d candidates (scoring pipeline): %s",
        len(handles),
        handles,
    )

    if dry_run:
        logger.info("Dry run mode — skipping Apify call")
        return {"candidates": len(candidates), "run_id": None, "budget_ok": True, "updated": 0, "dry_run": True}

    with open(APIFY_CONFIG_PATH, encoding="utf-8") as f:
        apify_cfg = yaml.safe_load(f)

    following_cfg = apify_cfg["following_actor"]
    actor_input = following_cfg["input"].copy()
    if "twitterHandles" in actor_input:
        actor_input["twitterHandles"] = handles
    else:
        actor_input["handles"] = handles
    # 覆盖参数：只获取 profile，不拉取 following/followers 列表
    actor_input["getFollowing"] = False
    actor_input["getFollowers"] = False
    actor_input["maxItems"] = len(handles) * 2  # 留少量余量

    client = ApifyClient(APIFY_API_TOKEN)
    run = client.actor(following_cfg["actor_id"]).call(run_input=actor_input)
    run_id = run.get("id", "")
    usage_usd = float(run.get("usageTotalUsd") or 0.0)
    if usage_usd > 0:
        upsert_cost(date.today(), apify_cost_usd=usage_usd)

    dataset_id = run.get("defaultDatasetId")
    stats = {"updated": 0}
    if dataset_id:
        items = list(client.dataset(dataset_id).iterate_items())
        stats = _store_results(items)
        logger.info("Snapshot backfill complete: %s", stats)

    return {"candidates": len(candidates), "run_id": run_id, "budget_ok": True, **stats}


_shutdown_requested = False


def _signal_handler(signum, frame):
    global _shutdown_requested
    logger.info("Received signal %d, will exit after current cycle...", signum)
    _shutdown_requested = True


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Backfill follower snapshots for AI-filtered creators pending model scoring."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=FOLLOWER_REFRESH_BATCH_SIZE,
        help="Maximum number of creators to process in one run (default: %d)." % FOLLOWER_REFRESH_BATCH_SIZE,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print candidates without triggering Apify.",
    )
    parser.add_argument(
        "--duration-days",
        type=int,
        default=30,
        help="Total duration to keep running in days (default: 30).",
    )
    args = parser.parse_args()

    if args.dry_run:
        result = run_backfill(limit=args.batch_size, dry_run=True)
        logger.info("Dry-run result: %s", result)
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    start_time = datetime.now()
    end_time = start_time + timedelta(days=args.duration_days)
    interval_seconds = FOLLOWER_REFRESH_INTERVAL_DAYS * 86400

    logger.info(
        "Backfill worker started at %s, will run until %s (%d days).",
        start_time.strftime("%Y-%m-%d %H:%M:%S"),
        end_time.strftime("%Y-%m-%d %H:%M:%S"),
        args.duration_days,
    )

    while not _shutdown_requested:
        now = datetime.now()
        if now >= end_time:
            logger.info(
                "Duration limit reached (%d days). Exiting.",
                args.duration_days,
            )
            break

        try:
            result = run_backfill(limit=args.batch_size, dry_run=False)
            logger.info("Cycle result: %s", result)
        except Exception:
            logger.exception("Cycle failed")

        next_run = now + timedelta(seconds=interval_seconds)
        if next_run >= end_time:
            logger.info("Next cycle would exceed duration limit. Exiting.")
            break

        sleep_seconds = (next_run - datetime.now()).total_seconds()
        if sleep_seconds > 0:
            logger.info(
                "Sleeping %.0f seconds until next cycle at %s...",
                sleep_seconds,
                next_run.strftime("%Y-%m-%d %H:%M:%S"),
            )
            # 分段 sleep 以便更快响应 shutdown 信号
            while sleep_seconds > 0 and not _shutdown_requested:
                chunk = min(sleep_seconds, 60.0)
                time.sleep(chunk)
                sleep_seconds -= chunk

    logger.info("Backfill worker stopped.")
