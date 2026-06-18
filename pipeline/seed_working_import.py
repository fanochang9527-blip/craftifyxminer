"""将 seed_working.xlsx 中的合作中作者导入/更新到数据库。

标记：
  - is_seed = true          → 作为 sellability 模型种子
  - bd_decision = interested → 业务已确认适合合作
  - discovery_strategy = 'seed_working_import'
"""

import logging
from pathlib import Path

import pandas as pd

from db.connection import fetch_all, get_cursor
from pipeline.creator_detail_sync import sync_creator_detail
from pipeline.creator_dna import analyze_creator_dna
from pipeline.sps_scorer import score_creator

logger = logging.getLogger(__name__)


def _load_usernames(path: str | Path) -> list[str]:
    """Read xlsx and return normalized usernames (strip, lstrip '@', lower)."""
    df = pd.read_excel(path)
    if "username" not in df.columns:
        raise ValueError(f"Excel must contain 'username' column. Found: {list(df.columns)}")

    usernames = []
    for raw in df["username"]:
        if pd.isna(raw):
            continue
        u = str(raw).strip().lstrip("@").lower()
        if u:
            usernames.append(u)
    return usernames


def import_seed_working(path: str | Path) -> dict:
    """Import creators from seed_working.xlsx.

    Returns: {"total": int, "inserted": int, "updated": int, "existing": int}
    """
    usernames = _load_usernames(path)
    logger.info("Loaded %d usernames from %s", len(usernames), path)

    rows = fetch_all(
        "SELECT id, username, is_seed, bd_decision FROM creators WHERE username = ANY(%s)",
        (usernames,),
    )
    existing = {r["username"]: r for r in rows} if rows else {}

    inserted = updated = 0
    for u in usernames:
        if u in existing:
            with get_cursor() as cur:
                cur.execute(
                    """UPDATE creators
                       SET is_seed = true,
                           bd_decision = 'interested',
                           discovery_strategy = 'seed_working_import'
                       WHERE id = %s""",
                    (existing[u]["id"],),
                )
            updated += 1
            try:
                sync_creator_detail(existing[u]["id"], sync_source="seed_working_import")
                analyze_creator_dna(existing[u]["id"])
                score_creator(existing[u]["id"])
            except Exception:
                logger.exception("Failed to sync creator_detail/DNA/SPS for existing seed %s", u)
        else:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO creators
                           (username, platform, platform_account_id,
                            is_seed, bd_decision, discovery_strategy)
                       VALUES (%s, 'twitter', %s, true, 'interested', 'seed_working_import')
                       ON CONFLICT (platform, platform_account_id) DO UPDATE SET
                           username = EXCLUDED.username,
                           is_seed = true,
                           bd_decision = 'interested',
                           discovery_strategy = 'seed_working_import'
                       RETURNING id""",
                    (u, u),
                )
                row = cur.fetchone()
                new_creator_id = row["id"] if row else None
            inserted += 1
            if new_creator_id:
                try:
                    sync_creator_detail(new_creator_id, sync_source="seed_working_import")
                    analyze_creator_dna(new_creator_id)
                    score_creator(new_creator_id)
                except Exception:
                    logger.exception("Failed to sync creator_detail/DNA/SPS for new seed %s", u)

    logger.info(
        "Import complete: total=%d, inserted=%d, updated=%d",
        len(usernames), inserted, updated,
    )
    return {
        "total": len(usernames),
        "inserted": inserted,
        "updated": updated,
        "existing": len(existing),
    }
