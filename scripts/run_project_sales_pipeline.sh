#!/usr/bin/env bash
# 项目级销量预测一键流水线
# 流程：清洗 汇总.xlsx -> 导入 projects -> Apify 同步创作者信息 -> 训练项目级模型 -> 项目级评分

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 激活虚拟环境
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "Error: .venv not found. Please create and activate the virtual environment first."
    exit 1
fi

SUMMARY_XLSX="${1:-汇总.xlsx}"
CLEANED_CSV="${2:-data/汇总_cleaned.csv}"

echo "====================================="
echo "项目级销量预测流水线"
echo "====================================="
echo "输入: $SUMMARY_XLSX"
echo "清洗输出: $CLEANED_CSV"
echo ""

# 1. 数据清洗
echo "[1/5] 清洗 汇总.xlsx ..."
python3 scripts/clean_summary_xlsx.py "$SUMMARY_XLSX" "$CLEANED_CSV"
echo ""

# 2. 清空并导入 projects 表
echo "[2/5] 清空并导入 projects 表 ..."
python3 - <<PY
from db.connection import execute
execute('TRUNCATE TABLE projects RESTART IDENTITY CASCADE')
execute('TRUNCATE TABLE project_scores RESTART IDENTITY CASCADE')
print('Projects and project_scores truncated.')
PY
python3 pipeline/project_import.py "$CLEANED_CSV"
echo ""

# 3. Apify 同步创作者信息
echo "[3/5] 通过 Apify 同步创作者信息 ..."
python3 pipeline/project_creator_sync.py
echo ""

# 4. 训练项目级模型
echo "[4/5] 训练项目级销量预测模型 ..."
python3 -m pipeline.project_sps_model train
echo ""

# 5. 项目级评分
echo "[5/5] 项目级评分并写入 project_scores ..."
python3 pipeline/project_scorer.py
echo ""

echo "====================================="
echo "流水线完成"
echo "====================================="

# 输出关键统计
python3 - <<PY
from db.connection import fetch_one
project_cnt = fetch_one('SELECT COUNT(*) as cnt FROM projects')['cnt']
score_cnt = fetch_one('SELECT COUNT(*) as cnt FROM project_scores')['cnt']
stats = fetch_one('''
    SELECT MIN(sps_score) as min_sps, MAX(sps_score) as max_sps, AVG(sps_score) as avg_sps,
           MIN(predicted_sales) as min_pred, MAX(predicted_sales) as max_pred, AVG(predicted_sales) as avg_pred
    FROM project_scores
''')
print(f"Projects: {project_cnt}")
print(f"Project scores: {score_cnt}")
print(f"SPS score range: {stats['min_sps']:.2f} - {stats['max_sps']:.2f} (avg: {stats['avg_sps']:.2f})")
print(f"Predicted sales range: {stats['min_pred']:.2f} - {stats['max_pred']:.2f} (avg: {stats['avg_pred']:.2f})")
PY
