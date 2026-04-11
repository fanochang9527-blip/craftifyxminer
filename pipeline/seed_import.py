"""Phase 1: 种子数据导入 — 读取 CSV 或权威 xlsx, 写入 creators 表, 同时运行自动分类。

支持：
  - CSV：含 creator_type 或 category（中文）
  - xlsx：与 data/创作者账号链接及销量收集.xlsx 同构（twitter_handle, category, main_link, total_sales 等）

去重与唯一键（与 ``seed_file_loader`` 一致）：
  - 每条记录由 ``(platform, platform_account_id)`` 唯一标识；未给平台时默认 ``twitter``；
    未给账号 ID 时用规范化后的 ``username``（handle）。
  - 同一键多行合作销售数据：保留 **成交笔数**（``transaction_count`` / 列名 ``成交笔数``）最多的一行；
    并列时保留 ``total_sales`` 较大行。

导入后自动执行：自动分类(写入 creator_type_auto) + bio 规则建议生成。
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd
import yaml

from config.settings import BIO_RULES_PATH, CREATOR_TYPES
from db.connection import get_cursor
from pipeline.bio_rule_filter import BioRuleFilter
from pipeline.seed_file_loader import load_seed_dataframe
from pipeline.type_classifier import classify_creator

logger = logging.getLogger(__name__)

CATEGORY_TO_CREATOR_TYPE: dict[str, str] = {
    "A-官方IP": "game_creator",
    "B-原创OC": "oc_creator",
    "C-虚拟IP": "vtuber",
    "E-二创IP": "fan_artist",
}


def _validate_creator_type(df: pd.DataFrame) -> None:
    """Ensure df has a valid creator_type column.

    If CSV has a 'category' column (Chinese) but no 'creator_type',
    auto-map using CATEGORY_TO_CREATOR_TYPE.
    """
    if "creator_type" not in df.columns:
        if "category" in df.columns:
            df["creator_type"] = df["category"].map(CATEGORY_TO_CREATOR_TYPE).fillna("unknown")
            mapped = df["category"].map(CATEGORY_TO_CREATOR_TYPE)
            unmapped = df.loc[mapped.isna() & df["category"].notna(), "category"].unique()
            if len(unmapped) > 0:
                logger.warning("Unmapped category values defaulted to 'unknown': %s", list(unmapped))
            logger.info("Auto-mapped 'category' -> 'creator_type': %s", df["creator_type"].value_counts().to_dict())
        else:
            raise ValueError(
                "CSV must include 'creator_type' or 'category' column. "
                f"Valid creator_type values: {', '.join(CREATOR_TYPES)}"
            )

    invalid = set(df["creator_type"].dropna().unique()) - set(CREATOR_TYPES)
    if invalid:
        raise ValueError(
            f"Invalid creator_type values: {invalid}. "
            f"Valid values: {', '.join(CREATOR_TYPES)}"
        )


def _generate_bio_rule_suggestions(df: pd.DataFrame) -> int:
    """Scan new seeds' bios for keywords not in current rules.

    Writes suggestions to config/bio_rules_suggestions.yaml for human review.
    Returns number of new suggestions found.
    """
    bf = BioRuleFilter()
    suggestions: dict[str, list[str]] = {
        "new_link_domains": [],
        "new_identity_keywords": [],
        "new_action_keywords": [],
    }

    known_links = set()
    for group in bf.rules.get("link_dna", {}).values():
        known_links.update(d.lower() for d in group)

    known_identity = set(bf._identity_keywords)
    known_action = set(bf._action_keywords)

    for _, row in df.iterrows():
        bio = str(row.get("bio", "") or "").lower()
        website = str(row.get("website", "") or "").lower()

        for domain_fragment in _extract_domains(f"{bio} {website}"):
            if domain_fragment not in known_links and domain_fragment not in suggestions["new_link_domains"]:
                suggestions["new_link_domains"].append(domain_fragment)

    total = sum(len(v) for v in suggestions.values())
    if total > 0:
        out_path = BIO_RULES_PATH.parent / "bio_rules_suggestions.yaml"
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.dump(suggestions, f, allow_unicode=True, default_flow_style=False)
        logger.info("Generated %d bio rule suggestions → %s", total, out_path)

    return total


def _extract_domains(text: str) -> list[str]:
    """Extract domain-like fragments from text (simplified)."""
    import re
    domains = re.findall(r'(?:https?://)?([a-z0-9][-a-z0-9]*\.[a-z]{2,}(?:\.[a-z]{2,})?)', text)
    skip = {"t.co", "twitter.com", "x.com", "pic.twitter.com"}
    return [d for d in domains if d not in skip]


def import_seeds(path: str, *, skip_post_pipeline: bool = False) -> dict:
    """Read CSV or xlsx and upsert seed creators into the database.

    Expected columns: username, creator_type **or** category (中文)
    Optional: total_sales, bio, website, followers, following, tweets_count, has_merch_experience

    If ``skip_post_pipeline`` is True, skip deep scrape / features / model retrain (faster for DB-only rebuilds).

    Returns a summary dict including ``load_stats`` (``raw_rows``, ``dropped_empty_handle``,
    ``rows_after_dedupe``, ``merged_duplicate_rows``, ``source``).
    """
    df, load_stats = load_seed_dataframe(path)
    required = {"username"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Seed file missing required columns: {missing}")

    _validate_creator_type(df)

    if "total_sales" not in df.columns:
        df["total_sales"] = 0.0

    inserted = updated = 0

    for _, row in df.iterrows():
        username = str(row["username"]).strip().lstrip("@").lower()
        if not username:
            continue

        platform = str(row.get("platform", "twitter") or "twitter").strip().lower() or "twitter"
        platform_account_id = str(row.get("platform_account_id", "") or "").strip().lower() or username
        txn_count = int(row.get("transaction_count", 0) or 0)

        manual_type = str(row.get("creator_type", "unknown"))
        bio = str(row.get("bio", "") or "")
        website = str(row.get("website", "") or "")

        auto_type = classify_creator(bio=bio, website=website)

        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO creators
                       (username, bio, website, followers, following, tweets_count,
                        total_sales, sales_transaction_count, has_merch_experience, is_seed,
                        creator_type_manual, creator_type_auto, discovery_strategy,
                        platform, platform_account_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s, 'csv_import', %s, %s)
                   ON CONFLICT (platform, platform_account_id) DO UPDATE SET
                       username = EXCLUDED.username,
                       total_sales = EXCLUDED.total_sales,
                       sales_transaction_count = EXCLUDED.sales_transaction_count,
                       is_seed = true,
                       creator_type_manual = EXCLUDED.creator_type_manual,
                       creator_type_auto = EXCLUDED.creator_type_auto,
                       discovery_strategy = 'csv_import',
                       bio = COALESCE(NULLIF(EXCLUDED.bio, ''), creators.bio),
                       website = COALESCE(NULLIF(EXCLUDED.website, ''), creators.website)
                   RETURNING (xmax = 0) AS is_insert""",
                (
                    username,
                    bio,
                    website,
                    int(row.get("followers", 0) or 0),
                    int(row.get("following", 0) or 0),
                    int(row.get("tweets_count", 0) or 0),
                    float(row.get("total_sales", 0) or 0),
                    txn_count,
                    bool(row.get("has_merch_experience", False)),
                    manual_type,
                    auto_type,
                    platform,
                    platform_account_id,
                ),
            )
            result = cur.fetchone()
            if result and result["is_insert"]:
                inserted += 1
            else:
                updated += 1

    suggestions = _generate_bio_rule_suggestions(df)

    summary = {
        "total": len(df),
        "inserted": inserted,
        "updated": updated,
        "bio_rule_suggestions": suggestions,
        "load_stats": load_stats,
    }
    logger.info("Seed import complete: %s", summary)

    # Post-import pipeline: deep scrape → features → model retrain
    usernames = [str(r["username"]).strip().lstrip("@").lower() for _, r in df.iterrows() if r.get("username")]
    if not skip_post_pipeline:
        _post_import_pipeline(usernames, summary)
    else:
        logger.info("Skipping post-import pipeline (--skip-post-pipeline)")

    return summary


def _post_import_pipeline(usernames: list[str], summary: dict) -> None:
    """Trigger deep scrape, feature computation and model retraining for imported seeds."""
    from pipeline.deep_scrape import trigger_seed_deep_scrape
    from pipeline.feature_engine import compute_features_for_creator
    from db.connection import fetch_all

    logger.info("Starting post-import pipeline for %d seeds", len(usernames))

    try:
        scrape_result = trigger_seed_deep_scrape(usernames)
        summary["deep_scrape"] = scrape_result
        logger.info("Seed deep scrape: %s", scrape_result)
    except Exception:
        logger.exception("Seed deep scrape failed — continuing with existing data")

    seed_ids = fetch_all(
        "SELECT id FROM creators WHERE username = ANY(%s) AND is_seed = true",
        (usernames,),
    )
    features_computed = 0
    for row in seed_ids:
        try:
            compute_features_for_creator(row["id"])
            features_computed += 1
        except Exception:
            logger.exception("Feature computation failed for creator %d", row["id"])
    summary["features_computed"] = features_computed
    logger.info("Computed features for %d seeds", features_computed)

    try:
        from pipeline.sps_model import train_model as train_sales_model

        train_result = train_sales_model()
        summary["model_retrain"] = {"sales_model": train_result}
        logger.info("Sales model retrained: %s", train_result)
    except ImportError:
        logger.warning("sps_model module not yet available — skipping model retrain")
    except Exception:
        logger.exception("Model retraining failed")

    try:
        from pipeline.sellability_model import train_model as train_sellability_model

        sellability_result = train_sellability_model()
        summary.setdefault("model_retrain", {})["sellability_model"] = sellability_result
        logger.info("Sellability model retrained: %s", sellability_result)
    except ImportError:
        logger.warning("sellability_model module not yet available — skipping sellability retrain")
    except Exception:
        logger.exception("Sellability model retraining failed")


def main():
    parser = argparse.ArgumentParser(description="Import seed creators from CSV or xlsx")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--csv", help="Path to seed CSV")
    g.add_argument(
        "--xlsx",
        help="Path to seed xlsx (e.g. data/创作者账号链接及销量收集.xlsx)",
    )
    parser.add_argument(
        "--skip-post-pipeline",
        action="store_true",
        help="Skip deep scrape / features / model retrain after import (faster for DB rebuilds)",
    )
    args = parser.parse_args()
    path = args.csv or args.xlsx

    logging.basicConfig(level=logging.INFO)
    result = import_seeds(path, skip_post_pipeline=args.skip_post_pipeline)
    print(
        f"Imported {result['total']} seeds: "
        f"inserted={result['inserted']}, updated={result['updated']}, "
        f"bio_suggestions={result['bio_rule_suggestions']}"
    )
    ls = result.get("load_stats") or {}
    if ls:
        print(
            "  load_stats:",
            f"source={ls.get('source')}, raw_rows={ls.get('raw_rows')}, "
            f"dropped_empty_handle={ls.get('dropped_empty_handle')}, "
            f"rows_after_dedupe={ls.get('rows_after_dedupe')}, "
            f"merged_duplicate_rows={ls.get('merged_duplicate_rows')}",
        )


if __name__ == "__main__":
    main()
