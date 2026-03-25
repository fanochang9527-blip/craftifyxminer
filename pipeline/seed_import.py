"""Phase 1: 种子数据导入 — 读取 CSV, 按 total_sales 打 Tier 标签, 写入 creators 表。"""

import argparse
import logging
import sys

import pandas as pd

from db.connection import get_cursor

logger = logging.getLogger(__name__)

TIER_THRESHOLDS = [
    ("S", 2000),
    ("A", 500),
    ("B", 100),
]


def classify_tier(total_sales: float) -> str:
    for tier, threshold in TIER_THRESHOLDS:
        if total_sales > threshold:
            return tier
    return "C"


def import_seeds(csv_path: str) -> dict:
    """Read CSV and upsert seed creators into the database.

    Expected CSV columns: username, total_sales (optional: bio, website,
    followers, following, tweets_count, has_merch_experience).
    Returns tier distribution stats.
    """
    df = pd.read_csv(csv_path)
    required = {"username"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    if "total_sales" not in df.columns:
        df["total_sales"] = 0.0

    df["seed_tier"] = df["total_sales"].apply(classify_tier)

    stats = df["seed_tier"].value_counts().to_dict()
    inserted = updated = 0

    for _, row in df.iterrows():
        username = str(row["username"]).strip().lstrip("@").lower()
        if not username:
            continue

        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO creators
                       (username, bio, website, followers, following, tweets_count,
                        total_sales, has_merch_experience, is_seed, seed_tier)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s)
                   ON CONFLICT (username) DO UPDATE SET
                       total_sales = EXCLUDED.total_sales,
                       is_seed = true,
                       seed_tier = EXCLUDED.seed_tier,
                       bio = COALESCE(NULLIF(EXCLUDED.bio, ''), creators.bio),
                       website = COALESCE(NULLIF(EXCLUDED.website, ''), creators.website)
                   RETURNING (xmax = 0) AS is_insert""",
                (
                    username,
                    str(row.get("bio", "") or ""),
                    str(row.get("website", "") or ""),
                    int(row.get("followers", 0) or 0),
                    int(row.get("following", 0) or 0),
                    int(row.get("tweets_count", 0) or 0),
                    float(row.get("total_sales", 0) or 0),
                    bool(row.get("has_merch_experience", False)),
                    row["seed_tier"],
                ),
            )
            result = cur.fetchone()
            if result and result["is_insert"]:
                inserted += 1
            else:
                updated += 1

    summary = {
        "total": len(df),
        "inserted": inserted,
        "updated": updated,
        "tier_distribution": stats,
    }
    logger.info("Seed import complete: %s", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Import seed creators from CSV")
    parser.add_argument("--csv", required=True, help="Path to merged_creators.csv")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    result = import_seeds(args.csv)
    print(f"Imported {result['total']} seeds: {result['tier_distribution']}")


if __name__ == "__main__":
    main()
