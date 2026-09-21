#!/usr/bin/env python3
"""
迁移旧版 model_evaluations 数据到新版 schema。

变化:
  - 新增 model_name VARCHAR(20)  -> 置为 NULL（旧数据无此信息）
  - 删除 sps_threshold            -> 丢弃该列数据

用法:
  cd /opt/craftifyxminer
  .venv/bin/python scripts/migrate_model_evaluations.py \
      --backup-sql backups/pre_deploy_data_only_20260527_145157.sql
"""

import argparse
import re
import sys
from pathlib import Path

# 确保能导入项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config.settings  # noqa: F401, E402
from db.connection import get_cursor  # noqa: E402

INSERT_RE = re.compile(
    r"INSERT INTO public\.model_evaluations \("
    r"id, evaluated_at, model_version, n_seeds, n_predictions, n_bd_reviewed, "
    r"n_interested, n_rejected, recall, precision_score, f2_score, "
    r"precision_at_250, spearman_corr, r2, mae, sps_threshold, notes\) "
    r"VALUES \((.+?)\);$"
)


def parse_row(values_str: str) -> tuple:
    """
    解析 VALUES 字符串中的 17 个字段，返回用于新表插入的 16 个字段。
    model_name 置为 NULL（第 2 位），跳过 sps_threshold（原第 16 位）。
    """
    # 用简单的状态机按逗号拆分，但需跳过字符串/JSON 内部的逗号
    parts = []
    current = []
    in_string = False
    in_json = False
    json_depth = 0
    i = 0
    chars = list(values_str)
    while i < len(chars):
        ch = chars[i]
        if ch == "'" and (i == 0 or chars[i - 1] != "\\"):
            in_string = not in_string
            current.append(ch)
        elif ch == "{" and not in_string:
            in_json = True
            json_depth += 1
            current.append(ch)
        elif ch == "}" and not in_string and in_json:
            json_depth -= 1
            if json_depth == 0:
                in_json = False
            current.append(ch)
        elif ch == "," and not in_string and not in_json:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current).strip())

    if len(parts) != 17:
        raise ValueError(f"Expected 17 columns, got {len(parts)}: {parts}")

    # 新列顺序: id, model_name, evaluated_at, model_version, n_seeds,
    #           n_predictions, n_bd_reviewed, n_interested, n_rejected,
    #           recall, precision_score, f2_score, precision_at_250,
    #           spearman_corr, r2, mae, notes
    new_parts = [
        parts[0],   # id
        "NULL",     # model_name (新增，无旧数据)
        parts[1],   # evaluated_at
        parts[2],   # model_version
        parts[3],   # n_seeds
        parts[4],   # n_predictions
        parts[5],   # n_bd_reviewed
        parts[6],   # n_interested
        parts[7],   # n_rejected
        parts[8],   # recall
        parts[9],   # precision_score
        parts[10],  # f2_score
        parts[11],  # precision_at_250
        parts[12],  # spearman_corr
        parts[13],  # r2
        parts[14],  # mae
        parts[16],  # notes (跳过原 sps_threshold parts[15])
    ]
    return tuple(new_parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-sql", required=True, help="纯数据备份 SQL 文件路径")
    args = parser.parse_args()

    sql_path = Path(args.backup_sql)
    if not sql_path.exists():
        print(f"ERROR: File not found: {sql_path}")
        sys.exit(1)

    rows = []
    with open(sql_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = INSERT_RE.match(line)
            if m:
                try:
                    row = parse_row(m.group(1))
                    rows.append(row)
                except ValueError as e:
                    print(f"WARN: 跳过无法解析的行: {e}")

    if not rows:
        print("未找到 model_evaluations 数据，无需迁移。")
        sys.exit(0)

    print(f"从备份中提取到 {len(rows)} 条 model_evaluations 记录。")

    insert_sql = """
        INSERT INTO model_evaluations (
            id, model_name, evaluated_at, model_version, n_seeds,
            n_predictions, n_bd_reviewed, n_interested, n_rejected,
            recall, precision_score, f2_score, precision_at_250,
            spearman_corr, r2, mae, notes
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s
        ) ON CONFLICT (id) DO NOTHING
    """

    inserted = 0
    skipped = 0
    with get_cursor() as cur:
        for row in rows:
            try:
                cur.execute(insert_sql, row)
                if cur.rowcount:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"ERROR 插入失败 id={row[0]}: {e}")
                skipped += 1

    print(f"迁移完成: 插入 {inserted} 条, 跳过 {skipped} 条。")


if __name__ == "__main__":
    main()
