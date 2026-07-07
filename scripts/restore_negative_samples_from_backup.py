#!/usr/bin/env python3
"""从数据库备份中恢复 BD 负样本创作者及其特征到当前数据库。

用途：全量重置后当前数据库只有正样本，sellability 模型退化为 DummyClassifier。
本脚本从旧备份中找出 bd_decision 为 rejected_unfit / rejected_not_creator 的创作者，
连同其 creator_features 一起导入当前数据库，使 sellability 模型获得负样本。

用法：
    .venv/bin/python scripts/restore_negative_samples_from_backup.py \
        backups/craftifyx_miner_20260706_152043.sql.gz --dry-run

参数：
    --dry-run   只输出将要导入的记录数，不写入数据库
"""

from __future__ import annotations

import argparse
import gzip
import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.connection import fetch_all, get_cursor

logger = logging.getLogger(__name__)

NEGATIVE_DECISIONS = {"rejected_unfit", "rejected_not_creator"}


def _open_backup(backup_path: str):
    if backup_path.endswith(".gz"):
        return gzip.open(backup_path, "rt", encoding="utf-8", errors="replace")
    return open(backup_path, "r", encoding="utf-8", errors="replace")


def _parse_copy_block(backup_path: str, table_name: str) -> tuple[list[str], list[dict[str, str]]]:
    """解析 pg_dump 文本备份中指定表的 COPY 块，返回 (列名, 行字典列表)。"""
    columns: list[str] = []
    rows: list[dict[str, str]] = []
    prefix = f"COPY public.{table_name} ("
    in_copy = False

    with _open_backup(backup_path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith(prefix):
                cols_part = line[len(prefix) :]
                cols_part = cols_part.split(") FROM stdin")[0]
                columns = [c.strip() for c in cols_part.split(",")]
                in_copy = True
                continue
            if in_copy:
                if line == "\\.":
                    break
                parts = line.split("\t")
                if len(parts) != len(columns):
                    logger.debug("Skipping malformed line in %s: %d parts vs %d cols", table_name, len(parts), len(columns))
                    continue
                rows.append(dict(zip(columns, parts)))

    return columns, rows


def _collect_creators(
    backup_path: str, only_negative: bool = True
) -> tuple[list[dict[str, str]], dict[int, dict[str, str]]]:
    """从备份中提取 creators 及其 features。

    Args:
        only_negative: True 只取 rejected 负样本；False 取全部 creators。
    """
    logger.info("Parsing creators from backup...")
    _, creator_rows = _parse_copy_block(backup_path, "creators")
    logger.info("Parsed %d creators", len(creator_rows))

    if only_negative:
        selected = [
            r for r in creator_rows
            if (r.get("bd_decision") or "").strip() in NEGATIVE_DECISIONS
        ]
        logger.info("Found %d negative creators", len(selected))
    else:
        selected = creator_rows
        logger.info("Selecting all %d creators", len(selected))

    logger.info("Parsing creator_features from backup...")
    _, feature_rows = _parse_copy_block(backup_path, "creator_features")
    logger.info("Parsed %d creator_features", len(feature_rows))

    features_by_creator: dict[int, dict[str, str]] = {}
    for r in feature_rows:
        try:
            cid = int(r["creator_id"])
        except (KeyError, ValueError):
            continue
        features_by_creator[cid] = r

    return selected, features_by_creator


def _prepare_value(value: str | None, default: Any = None) -> Any:
    r"""将 COPY 中的 \\N 转换为 None，空字符串按需处理。"""
    if value is None or value == "\\N":
        return default
    return value


def _build_creator_insert_row(row: dict[str, str]) -> dict[str, Any]:
    """从备份行构造当前 creators 表可插入的字典。"""
    username = (row.get("username") or "").strip().lower()
    return {
        "username": username,
        "platform": _prepare_value(row.get("platform"), "twitter"),
        "platform_account_id": _prepare_value(row.get("platform_account_id"), username),
        "sales_transaction_count": int(_prepare_value(row.get("sales_transaction_count"), 0) or 0),
        "followers": int(_prepare_value(row.get("followers"), 0) or 0) if _prepare_value(row.get("followers")) else None,
        "following": int(_prepare_value(row.get("following"), 0) or 0) if _prepare_value(row.get("following")) else None,
        "tweets_count": int(_prepare_value(row.get("tweets_count"), 0) or 0) if _prepare_value(row.get("tweets_count")) else None,
        "bio": _prepare_value(row.get("bio"), ""),
        "website": _prepare_value(row.get("website"), ""),
        "account_age": int(_prepare_value(row.get("account_age"), 0) or 0) if _prepare_value(row.get("account_age")) else None,
        "is_seed": (_prepare_value(row.get("is_seed"), "false") or "false").lower() == "true",
        "creator_type_manual": _prepare_value(row.get("creator_type_manual")),
        "creator_type_auto": _prepare_value(row.get("creator_type_auto")),
        "total_sales": float(_prepare_value(row.get("total_sales"), 0) or 0),
        "has_merch_experience": (_prepare_value(row.get("has_merch_experience"), "false") or "false").lower() == "true",
        "discovered_date": _prepare_value(row.get("discovered_date")),
        "discovered_via": _prepare_value(row.get("discovered_via")),
        "discovery_strategy": "restored_from_backup",
        "anchor_seed": _prepare_value(row.get("anchor_seed")),
        "bd_status": _prepare_value(row.get("bd_status"), "pending"),
        "bd_assigned_to": _prepare_value(row.get("bd_assigned_to")),
        "bd_decision": _prepare_value(row.get("bd_decision")),
        "bd_decision_note": _prepare_value(row.get("bd_decision_note")),
        "creator_segment": _prepare_value(row.get("creator_segment")),
        "last_bd_update": _prepare_value(row.get("last_bd_update")),
        "last_scraped_as_anchor": _prepare_value(row.get("last_scraped_as_anchor")),
        "first_seen_at": _prepare_value(row.get("first_seen_at")),
        "last_follower_refresh_at": _prepare_value(row.get("last_follower_refresh_at")),
    }


def _build_feature_insert_row(feature_row: dict[str, str], new_creator_id: int, feature_cols: list[str]) -> dict[str, Any]:
    """从备份行构造当前 creator_features 表可插入的字典。"""
    out: dict[str, Any] = {"creator_id": new_creator_id}
    for col in feature_cols:
        if col in ("id", "creator_id"):
            continue
        val = _prepare_value(feature_row.get(col))
        if val is None or val == "":
            out[col] = None
        else:
            try:
                # 先尝试 float，整数也能被正确解析
                out[col] = float(val)
            except ValueError:
                # 布尔值在 pg_dump 中为 t/f
                if val.lower() == "t":
                    out[col] = True
                elif val.lower() == "f":
                    out[col] = False
                else:
                    out[col] = val
    return out


def restore_negative_samples(backup_path: str, dry_run: bool = False, all_creators: bool = False) -> dict:
    negative_creators, features_by_creator = _collect_creators(
        backup_path, only_negative=not all_creators
    )

    if not negative_creators:
        logger.warning("No negative creators found in backup")
        return {"found": 0, "skipped_existing": 0, "inserted_creators": 0, "inserted_features": 0}

    # 查询当前已存在的 username 和 platform_account_id，避免重复导入
    existing_rows = fetch_all("SELECT username, platform_account_id FROM creators")
    existing_usernames = {r["username"].lower() for r in existing_rows}
    existing_platform_ids = {(r["platform_account_id"] or "").lower() for r in existing_rows}
    logger.info("Current DB has %d creators", len(existing_rows))

    # 获取当前 creator_features 的列名
    feature_cols_info = fetch_all(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'creator_features' ORDER BY ordinal_position"
    )
    feature_cols = [c["column_name"] for c in feature_cols_info]

    to_insert_creators = []
    backup_id_to_new_id: dict[int, int] = {}
    skipped_existing = 0

    for row in negative_creators:
        username = (row.get("username") or "").strip().lower()
        platform_account_id = (row.get("platform_account_id") or username).strip().lower()
        if not username:
            continue
        if username in existing_usernames or platform_account_id in existing_platform_ids:
            skipped_existing += 1
            continue
        to_insert_creators.append(row)

    logger.info(
        "Ready to insert %d creators (%d skipped due to existing username/platform_account_id)",
        len(to_insert_creators), skipped_existing
    )

    if dry_run:
        feature_count = sum(
            1 for r in to_insert_creators
            if int(r.get("id", 0)) in features_by_creator
        )
        logger.info("DRY-RUN: would insert %d creators and %d features", len(to_insert_creators), feature_count)
        return {
            "found": len(negative_creators),
            "skipped_existing": skipped_existing,
            "inserted_creators": 0,
            "inserted_features": 0,
        }

    inserted_creators = 0
    inserted_features = 0
    batch_size = 500

    creator_insert_cols = list(_build_creator_insert_row({}).keys())
    feature_insert_cols = [c for c in feature_cols if c not in ("id",)]

    # 批量插入 creators，按 username 匹配返回的 id
    for i in range(0, len(to_insert_creators), batch_size):
        batch = to_insert_creators[i : i + batch_size]
        placeholders = []
        values = []
        for row in batch:
            row_values = list(_build_creator_insert_row(row).values())
            ph = "(" + ", ".join(["%s"] * len(row_values)) + ")"
            placeholders.append(ph)
            values.extend(row_values)

        sql = (
            "INSERT INTO creators (" + ", ".join(creator_insert_cols) + ") VALUES "
            + ", ".join(placeholders)
            + " RETURNING id, username"
        )
        with get_cursor() as cur:
            cur.execute(sql, values)
            returned = cur.fetchall()

        username_to_new_id = {r["username"].lower(): r["id"] for r in returned}
        for row in batch:
            backup_id = int(row.get("id", 0))
            username = (row.get("username") or "").strip().lower()
            new_id = username_to_new_id.get(username)
            if new_id:
                backup_id_to_new_id[backup_id] = new_id
                inserted_creators += 1

    logger.info("Inserted %d creators", inserted_creators)

    # 批量插入对应的 creator_features
    feature_rows_to_insert = []
    for backup_id, new_id in backup_id_to_new_id.items():
        feature_row = features_by_creator.get(backup_id)
        if not feature_row:
            continue
        feature_values = _build_feature_insert_row(feature_row, new_id, feature_cols)
        feature_rows_to_insert.append([feature_values.get(c) for c in feature_insert_cols])
        inserted_features += 1

    if feature_rows_to_insert:
        feature_sql = (
            "INSERT INTO creator_features (" + ", ".join(feature_insert_cols) + ") VALUES ("
            + ", ".join(["%s"] * len(feature_insert_cols)) + ")"
        )
        with get_cursor(dict_cursor=False) as cur:
            cur.executemany(feature_sql, feature_rows_to_insert)

    logger.info("Inserted %d creator_features", inserted_features)

    return {
        "found": len(negative_creators),
        "skipped_existing": skipped_existing,
        "inserted_creators": inserted_creators,
        "inserted_features": inserted_features,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore BD negative samples from backup")
    parser.add_argument("backup", help="Path to pg_dump text backup (.sql or .sql.gz)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument(
        "--all-creators",
        action="store_true",
        help="Restore all creators from backup, not just negative samples",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    stats = restore_negative_samples(args.backup, dry_run=args.dry_run, all_creators=args.all_creators)
    logger.info("Done: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
