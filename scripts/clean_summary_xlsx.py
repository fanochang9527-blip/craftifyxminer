#!/usr/bin/env python3
"""清洗 汇总.xlsx，输出项目级训练样本。

处理流程：
1. 只读取必要列，忽略 Excel 中嵌入的图片（如 产品图）。
2. 删除 订单产品数量 为 0 / 空 / 异常 的行。
3. 删除 定价(USD) 异常的行。
4. 保留包含 X / Twitter 链接的行（不再和 seed_file.csv 白名单匹配）。
5. 取第一个 X 链接作为 x_link，全部 X 链接拼接作为 ad_link。
6. 根据原始链接中平台数量标记 creator_is_multi_platform。
7. 输出清洗后的项目级样本（CSV）。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.utils.url_utils import (
    detect_platforms,
    extract_links,
    is_x_link,
)

logger = logging.getLogger(__name__)

# 汇总.xlsx 中需要用到的列名
SUMMARY_COLUMNS = [
    "打样编号",
    "领域",
    "产品属性",
    "定价(USD)",
    "订单产品数量",
    "创作者推荐链接（可单个/多个）",
]

# 输出列名（便于后续入库）
OUTPUT_COLUMNS = [
    "sku",
    "domain",
    "product_attribute",
    "price",
    "order_quantity",
    "ad_link",
    "ad_link_raw",
    "x_link",
    "creator_is_multi_platform",
]

# 人工确认无效的 X 链接（如账号已删除/冻结），清洗时直接丢弃对应行
INVALID_X_LINKS = {
    "https://x.com/lin_vt_",
}


def _extract_links(cell) -> list[str]:
    """从单元格值中提取一个或多个 URL。"""
    if pd.isna(cell):
        return []
    return extract_links(str(cell))


def _clean_price(value) -> float | None:
    """把 '$29.99' / '29.99' 等解析为 float；异常返回 None。"""
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "").replace(" ", "")
    try:
        price = float(text)
    except ValueError:
        return None
    if price <= 0:
        return None
    return price


def _clean_quantity(value) -> float | None:
    """把订单数量解析为 float；0 / 空 / 异常返回 None。"""
    if pd.isna(value):
        return None
    try:
        qty = float(value)
    except (ValueError, TypeError):
        return None
    if qty <= 0:
        return None
    return qty


def _clean_sku(value) -> str | None:
    """取 打样编号 单元格中所有非空行，用 " | " 拼接作为项目 sku。"""
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    return " | ".join(lines)


def _process_ad_link(cell) -> tuple[list[str], list[str], str | None, bool]:
    """处理创作者推荐链接单元格。

    返回：
        all_links: 提取到的所有链接
        x_links: 其中的 X / Twitter 链接
        x_link: 第一个 X 链接（用于 Apify 采集）
        is_multi_platform: 是否包含多个平台
    """
    if pd.isna(cell):
        return [], [], None, False

    all_links = _extract_links(cell)
    x_links = [link for link in all_links if is_x_link(link)]
    x_link = x_links[0] if x_links else None

    platforms = detect_platforms(cell)
    # 把 x 和 twitter 视为同一平台
    normalized_platforms = platforms - {"twitter"} if "x" in platforms else platforms
    is_multi_platform = len(normalized_platforms) > 1

    return all_links, x_links, x_link, is_multi_platform


def clean_summary_xlsx(
    input_path: str | Path,
    output_path: str | Path | None = None,
) -> pd.DataFrame:
    """清洗 汇总.xlsx 并返回清洗后的 DataFrame，可选写入 CSV。

    Args:
        input_path: 汇总.xlsx 路径。
        output_path: 可选，清洗结果输出路径（CSV）。

    Returns:
        清洗后的 DataFrame，列与 OUTPUT_COLUMNS 一致。
    """
    input_path = Path(input_path)

    logger.info("Reading %s with columns: %s", input_path, SUMMARY_COLUMNS)
    df = pd.read_excel(input_path, sheet_name="产品信息", usecols=SUMMARY_COLUMNS)
    raw_count = len(df)
    logger.info("Raw rows: %d", raw_count)

    # 1. 基础字段清洗
    df["sku"] = df["打样编号"].apply(_clean_sku)
    df["price"] = df["定价(USD)"].apply(_clean_price)
    df["order_quantity"] = df["订单产品数量"].apply(_clean_quantity)

    # 重命名/拷贝其他列
    df = df.rename(
        columns={
            "领域": "domain",
            "产品属性": "product_attribute",
        }
    )

    # 2. 删除 sku / price / order_quantity 为空的行
    null_sku = df["sku"].isna().sum()
    null_price = df["price"].isna().sum()
    null_quantity = df["order_quantity"].isna().sum()
    logger.info(
        "Null breakdown: sku=%d, price=%d, order_quantity=%d (rows may overlap)",
        null_sku, null_price, null_quantity,
    )
    df = df.dropna(subset=["sku", "price", "order_quantity"])
    after_basic = len(df)
    logger.info("After dropping null sku/price/quantity: %d (dropped %d)", after_basic, raw_count - after_basic)

    # 3. 删除枚举特征为空的行
    null_domain = df["domain"].isna().sum()
    null_attr = df["product_attribute"].isna().sum()
    logger.info("Null enums: domain=%d, product_attribute=%d", null_domain, null_attr)
    df = df.dropna(subset=["domain", "product_attribute"])
    after_enum = len(df)
    logger.info("After dropping null domain/product_attribute: %d (dropped %d)", after_enum, after_basic - after_enum)

    # 4. 链接处理：保留有 X 链接的行
    ad_link_col = "创作者推荐链接（可单个/多个）"
    empty_ad_link = df[ad_link_col].isna().sum()
    logger.info("Empty ad_link: %d", empty_ad_link)

    link_results = df[ad_link_col].apply(_process_ad_link)
    df["ad_link_raw"] = df[ad_link_col]
    df["ad_link"] = link_results.apply(lambda x: "\n".join(x[1]))  # X links joined
    df["x_link"] = link_results.apply(lambda x: x[2])
    df["creator_is_multi_platform"] = link_results.apply(lambda x: x[3])

    has_x_link = df["x_link"].notna()
    no_x_link = (~has_x_link).sum()
    logger.info("Rows with X link: %d, rows without X link: %d", has_x_link.sum(), no_x_link)

    df = df[has_x_link].copy()
    after_x_filter = len(df)
    logger.info("After X link filter: %d (dropped %d)", after_x_filter, after_enum - after_x_filter)

    # 过滤人工确认无效的 X 账号
    if INVALID_X_LINKS:
        before_invalid = len(df)
        df = df[~df["x_link"].isin(INVALID_X_LINKS)].copy()
        dropped_invalid = before_invalid - len(df)
        logger.info("After dropping invalid X links: %d (dropped %d)", len(df), dropped_invalid)

    # 5. 保留输出列
    df = df[OUTPUT_COLUMNS].copy()

    # 6. 去重：同一 sku 保留 order_quantity 最大的一行
    before_dedup = len(df)
    df = df.sort_values("order_quantity", ascending=False).drop_duplicates(
        subset=["sku"], keep="first"
    )
    after_dedup = len(df)
    logger.info("After dedup by sku: %d (dropped %d)", after_dedup, before_dedup - after_dedup)
    logger.info("Final cleaned rows: %d (total dropped from raw: %d)", after_dedup, raw_count - after_dedup)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        logger.info("Wrote cleaned data to %s", output_path)

    return df


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    import sys

    if len(sys.argv) >= 2:
        in_path = sys.argv[1]
        out_path = sys.argv[2] if len(sys.argv) >= 3 else "data/汇总_cleaned.csv"
    else:
        in_path = "汇总.xlsx"
        out_path = "data/汇总_cleaned.csv"

    clean_summary_xlsx(in_path, out_path)
