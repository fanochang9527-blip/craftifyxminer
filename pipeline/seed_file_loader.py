"""从 CSV/xlsx 加载种子 DataFrame（仅 pandas/openpyxl，不依赖 DB）。

唯一键：``(platform, platform_account_id)``。同一键多行合作销售记录时，保留
**成交笔数**（``transaction_count``）最大的一行；若相同再按 ``total_sales`` 较大者优先。
未提供 ``platform`` 时默认 ``twitter``；未提供 ``platform_account_id`` 时用规范化后的 ``username``。
"""

from __future__ import annotations

import logging
import numbers
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# 表头别名 → 内部列名（与 seed_import 写入 DB 的语义一致）
_SEED_COLUMN_ALIASES: dict[str, str] = {
    "归属平台": "platform",
    "创作者账号id": "platform_account_id",
    "账号id": "platform_account_id",
    "account_id": "platform_account_id",
    "platform_account_id": "platform_account_id",
    "成交笔数": "transaction_count",
    "订单数": "transaction_count",
    "sales_transactions": "transaction_count",
    "transaction_count": "transaction_count",
}


def _normalize_username(value: object) -> str:
    s = str(value).strip().lstrip("@").lower()
    if s in ("nan", "none", ""):
        return ""
    return s


def _normalize_platform(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "twitter"
    s = str(value).strip().lower()
    if not s or s in ("nan", "none"):
        return "twitter"
    if s in ("推特", "twitter", "x", "x.com"):
        return "twitter"
    return s


def _normalize_platform_account_id_cell(value: object) -> str:
    """合作方账号 ID：去掉空白；数值型转无小数字符串；再转小写与 username 规则一致。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if type(value) is bool:
        return ""
    if isinstance(value, numbers.Integral):
        return str(int(value)).strip().lower()
    if isinstance(value, numbers.Real):
        fv = float(value)
        if fv == int(fv):
            return str(int(fv)).strip().lower()
    s = str(value).strip()
    if s.lower() in ("nan", "none", ""):
        return ""
    return s.lower()


def _apply_seed_column_aliases(df: pd.DataFrame) -> pd.DataFrame:
    """将中文/别名列名映射为内部列名。"""
    rename: dict[str, str] = {}
    for c in df.columns:
        key = str(c).strip()
        if key in _SEED_COLUMN_ALIASES:
            rename[c] = _SEED_COLUMN_ALIASES[key]
    if rename:
        df = df.rename(columns=rename)
    return df


def dedupe_seeds_by_platform_account(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """按 (platform, platform_account_id) 去重：成交笔数优先，其次销售额。

    要求已有 ``username`` 列（一般为规范化后的 handle）。返回 (去重后的 df, 合并掉的行数)。
    """
    df = _apply_seed_column_aliases(df.copy())
    n_before = len(df)

    if "username" not in df.columns:
        raise ValueError("dedupe_seeds_by_platform_account requires a 'username' column")

    if "platform" not in df.columns:
        df["platform"] = "twitter"
    else:
        df["platform"] = df["platform"].map(_normalize_platform)

    if "platform_account_id" not in df.columns:
        df["platform_account_id"] = df["username"].map(_normalize_username)
    else:
        df["platform_account_id"] = df["platform_account_id"].map(_normalize_platform_account_id_cell)
        empty = df["platform_account_id"] == ""
        if empty.any():
            df.loc[empty, "platform_account_id"] = df.loc[empty, "username"].map(_normalize_username)

    if "transaction_count" not in df.columns:
        df["transaction_count"] = 0
    else:
        df["transaction_count"] = (
            pd.to_numeric(df["transaction_count"], errors="coerce").fillna(0).astype("int64")
        )

    if "total_sales" not in df.columns:
        df["total_sales"] = 0.0
    else:
        df["total_sales"] = pd.to_numeric(df["total_sales"], errors="coerce").fillna(0.0)

    df = df.sort_values(
        by=["transaction_count", "total_sales"],
        ascending=[False, False],
        kind="mergesort",
    )
    df = df.drop_duplicates(subset=["platform", "platform_account_id"], keep="first")
    merged = max(0, n_before - len(df))
    return df.reset_index(drop=True), merged


def load_seed_dataframe_from_xlsx(
    path: str | Path, *, sheet_name: str | int = 0
) -> tuple[pd.DataFrame, dict]:
    """Load 创作者账号链接及销量收集 风格 xlsx → DataFrame + ``load_stats`` 统计字典。"""
    path = Path(path)
    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    raw_rows = len(df)
    need = {"twitter_handle", "category"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"xlsx missing required columns {missing}; got {list(df.columns)}")

    df["username"] = df["twitter_handle"].map(_normalize_username)
    dropped_empty_handle = int((df["username"] == "").sum())
    df = df[df["username"] != ""]

    if "main_link" in df.columns:
        df["website"] = df["main_link"].fillna("").astype(str)
    else:
        df["website"] = ""

    if "total_sales" in df.columns:
        df["total_sales"] = pd.to_numeric(df["total_sales"], errors="coerce").fillna(0.0)
    else:
        df["total_sales"] = 0.0

    df, merged_duplicate_rows = dedupe_seeds_by_platform_account(df)
    rows_after_dedupe = len(df)

    load_stats: dict = {
        "source": "xlsx",
        "raw_rows": raw_rows,
        "dropped_empty_handle": dropped_empty_handle,
        "rows_after_dedupe": rows_after_dedupe,
        "merged_duplicate_rows": merged_duplicate_rows,
    }

    logger.info(
        "Seed file stats (xlsx): raw_rows=%d, dropped_empty_handle=%d, rows_after_dedupe=%d",
        raw_rows,
        dropped_empty_handle,
        rows_after_dedupe,
    )
    if merged_duplicate_rows > 0:
        logger.info(
            "Seed file (xlsx): merged %d duplicate (platform, platform_account_id) row(s) "
            "(kept max transaction_count, then total_sales)",
            merged_duplicate_rows,
        )

    return df, load_stats


def load_seed_dataframe(path: str | Path) -> tuple[pd.DataFrame, dict]:
    """Load CSV or xlsx into a dataframe ready for validation + DB import.

    Returns ``(df, load_stats)``. ``load_stats`` keys: ``source``, ``raw_rows``,
    ``dropped_empty_handle``, ``rows_after_dedupe``, ``merged_duplicate_rows`` (ints or None).
    """
    path = Path(path)
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xlsm"):
        return load_seed_dataframe_from_xlsx(path)
    if suf == ".xls":
        raise ValueError("Legacy .xls requires xlrd; convert to .xlsx or export CSV.")

    raw_df = pd.read_csv(path)
    raw_rows = len(raw_df)

    if "username" not in raw_df.columns:
        logger.info(
            "Seed file stats (csv): raw_rows=%d, dropped_empty_handle=n/a, rows_after_dedupe=n/a (no username column)",
            raw_rows,
        )
        return raw_df, {
            "source": "csv",
            "raw_rows": raw_rows,
            "dropped_empty_handle": None,
            "rows_after_dedupe": None,
            "merged_duplicate_rows": None,
        }

    df = raw_df.copy()
    df["username"] = df["username"].map(_normalize_username)
    dropped_empty_handle = int((df["username"] == "").sum())
    df = df[df["username"] != ""]

    df, merged_duplicate_rows = dedupe_seeds_by_platform_account(df)
    rows_after_dedupe = len(df)

    load_stats: dict = {
        "source": "csv",
        "raw_rows": raw_rows,
        "dropped_empty_handle": dropped_empty_handle,
        "rows_after_dedupe": rows_after_dedupe,
        "merged_duplicate_rows": merged_duplicate_rows,
    }

    logger.info(
        "Seed file stats (csv): raw_rows=%d, dropped_empty_handle=%d, rows_after_dedupe=%d",
        raw_rows,
        dropped_empty_handle,
        rows_after_dedupe,
    )
    if merged_duplicate_rows > 0:
        logger.info(
            "Seed file (csv): merged %d duplicate (platform, platform_account_id) row(s)",
            merged_duplicate_rows,
        )

    return df, load_stats
