"""定时任务编排 — APScheduler。"""

# TODO: 实现定时任务
# 08:00 - 生成当日锚点 (discovery.generate_daily_seeds)
# 08:10 - 触发 Apify L1 扫描 (discovery.trigger_l1_scan)
# Webhook 回调后自动: AI 过滤 -> 深度抓取 -> 指标计算 -> SPS 评分
# 23:00 - 生成日报数据, 更新成本统计
