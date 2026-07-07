#!/usr/bin/env python3
"""从数据库备份中恢复非 admin 用户到当前数据库。

适用场景：全量重置部署后，当前 users 表只有脚本新建的 admin，
需要把历史 BD/运营用户（yijing、yanbin 等）从备份恢复。

用法：
    .venv/bin/python scripts/restore_users_from_backup.py backups/craftifyx_miner_20260706_152043.sql.gz

参数：
    --dry-run   只输出将要恢复的用户，不写入数据库
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


def _open_backup(backup_path: str):
    if backup_path.endswith(".gz"):
        return gzip.open(backup_path, "rt", encoding="utf-8", errors="replace")
    return open(backup_path, "r", encoding="utf-8", errors="replace")


def _parse_users_copy(backup_path: str) -> list[dict[str, str]]:
    """解析备份中的 public.users COPY 块。"""
    rows: list[dict[str, str]] = []
    prefix = "COPY public.users ("
    in_copy = False
    columns: list[str] = []

    with _open_backup(backup_path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith(prefix):
                cols_part = line[len(prefix) :].split(") FROM stdin")[0]
                columns = [c.strip() for c in cols_part.split(",")]
                in_copy = True
                continue
            if in_copy:
                if line == "\\.":
                    break
                parts = line.split("\t")
                if len(parts) != len(columns):
                    continue
                rows.append(dict(zip(columns, parts)))

    return rows


def _prepare_value(value: str | None, default: Any = None) -> Any:
    r"""将 COPY 中的 \\N 转换为 None。"""
    if value is None or value == "\\N" or value == "":
        return default
    return value


def restore_users(backup_path: str, dry_run: bool = False) -> dict:
    rows = _parse_users_copy(backup_path)
    logger.info("Parsed %d users from backup", len(rows))

    # 过滤掉 admin，只恢复业务/BD 用户
    non_admin = [r for r in rows if (r.get("role") or "").strip() != "admin"]
    logger.info("Found %d non-admin users to restore", len(non_admin))

    if not non_admin:
        return {"parsed": len(rows), "restored": 0}

    current_usernames = {r["username"].lower() for r in fetch_all("SELECT username FROM users")}
    to_restore = [r for r in non_admin if (r.get("username") or "").strip().lower() not in current_usernames]
    logger.info("%d users already exist, will restore %d", len(non_admin) - len(to_restore), len(to_restore))

    if dry_run:
        logger.info("DRY-RUN: would restore %d users: %s", len(to_restore), [r.get("username") for r in to_restore])
        return {"parsed": len(rows), "restored": 0}

    insert_sql = """
        INSERT INTO users (id, username, password_hash, display_name, role, is_active,
                           locked_until, failed_attempts, last_login_at, password_changed_at, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            username = EXCLUDED.username,
            password_hash = EXCLUDED.password_hash,
            display_name = EXCLUDED.display_name,
            role = EXCLUDED.role,
            is_active = EXCLUDED.is_active,
            locked_until = EXCLUDED.locked_until,
            failed_attempts = EXCLUDED.failed_attempts,
            last_login_at = EXCLUDED.last_login_at,
            password_changed_at = EXCLUDED.password_changed_at,
            created_at = EXCLUDED.created_at
    """

    restored = 0
    for r in to_restore:
        values = (
            int(r["id"]),
            r["username"],
            r["password_hash"],
            _prepare_value(r.get("display_name")),
            r["role"],
            _prepare_value(r.get("is_active"), "true").lower() == "true",
            _prepare_value(r.get("locked_until")),
            int(_prepare_value(r.get("failed_attempts"), 0) or 0),
            _prepare_value(r.get("last_login_at")),
            _prepare_value(r.get("password_changed_at")),
            _prepare_value(r.get("created_at")),
        )
        with get_cursor(dict_cursor=False) as cur:
            cur.execute(insert_sql, values)
        restored += 1

    logger.info("Restored %d users", restored)
    return {"parsed": len(rows), "restored": restored}


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore non-admin users from backup")
    parser.add_argument("backup", help="Path to pg_dump text backup (.sql or .sql.gz)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    stats = restore_users(args.backup, dry_run=args.dry_run)
    logger.info("Done: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
