"""项目级样本导入：将清洗后的 汇总_cleaned.csv 写入 projects 表。

流程：
1. 读取 cleaned CSV（sku, domain, product_attribute, price, order_quantity, ad_link,
   ad_link_raw, x_link, creator_is_multi_platform）。
2. 基于 sku 生成确定性 project_id。
3. 逐行 upsert 到 projects 表（此时创作者特征字段为空，后续由 Apify 同步补齐）。
"""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.connection import get_cursor

logger = logging.getLogger(__name__)


def _generate_project_id(sku: str) -> str:
    """基于 sku 生成确定性 project_id。"""
    return hashlib.sha256(sku.encode("utf-8")).hexdigest()[:16]


def import_projects(cleaned_csv_path: str | Path) -> dict:
    """导入清洗后的项目样本到 projects 表。

    Returns:
        {"total": int, "inserted": int, "updated": int}
    """
    cleaned_path = Path(cleaned_csv_path)
    df = pd.read_csv(cleaned_path)
    logger.info("Loading %d cleaned project rows from %s", len(df), cleaned_path)

    inserted = updated = 0

    with get_cursor() as cur:
        for _, row in df.iterrows():
            sku = str(row["sku"]).strip()
            project_id = _generate_project_id(sku)

            cur.execute(
                """
                INSERT INTO projects
                    (project_id, sku, domain, product_attribute, price, order_quantity,
                     ad_link, ad_link_raw, x_link, creator_is_multi_platform)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id) DO UPDATE SET
                    sku = EXCLUDED.sku,
                    domain = EXCLUDED.domain,
                    product_attribute = EXCLUDED.product_attribute,
                    price = EXCLUDED.price,
                    order_quantity = EXCLUDED.order_quantity,
                    ad_link = EXCLUDED.ad_link,
                    ad_link_raw = EXCLUDED.ad_link_raw,
                    x_link = EXCLUDED.x_link,
                    creator_is_multi_platform = EXCLUDED.creator_is_multi_platform,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS is_insert
                """,
                (
                    project_id,
                    sku,
                    str(row["domain"]).strip() if pd.notna(row["domain"]) else None,
                    str(row["product_attribute"]).strip() if pd.notna(row["product_attribute"]) else None,
                    float(row["price"]),
                    float(row["order_quantity"]),
                    str(row.get("ad_link", "")).strip() if pd.notna(row.get("ad_link")) else None,
                    str(row.get("ad_link_raw", "")).strip() if pd.notna(row.get("ad_link_raw")) else None,
                    str(row.get("x_link", "")).strip() if pd.notna(row.get("x_link")) else None,
                    bool(row.get("creator_is_multi_platform", False)),
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
    }
    logger.info("Project import complete: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    csv_path = sys.argv[1] if len(sys.argv) > 1 else "data/汇总_cleaned.csv"
    result = import_projects(csv_path)
    print(
        f"Imported {result['total']} projects: "
        f"inserted={result['inserted']}, updated={result['updated']}"
    )
