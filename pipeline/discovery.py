"""每日发现引擎 — 动态锚点选择 + 10-20% 随机探索。"""

# TODO: 实现每日发现逻辑
# 1. generate_daily_seeds(): 80% 高价值 Seed + 20% 随机探索 (跨地域/跨品类/时间)
# 2. trigger_l1_scan(): 触发 Apify Following 扫描
# 3. 标记 discovery_strategy 字段
# 4. 写入 discovery_batches 表
