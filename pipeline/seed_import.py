"""Phase 1: 种子数据导入 — 读取 CSV, 按 total_sales 打 Tier 标签, 写入 creators 表。"""

# TODO: 实现种子导入逻辑
# 1. 读取 merged_creators.csv
# 2. 按 total_sales 划分 Tier: S(>$2000), A(>$500), B(>$100), C(其余)
# 3. 写入 creators 表, 标记 is_seed=true
# 4. 输出 Tier 分布统计

# 用法: python -m pipeline.seed_import --csv path/to/merged_creators.csv
