"""深度抓取触发 — AI 过滤通过的候选人, 使用 Residential Proxy 抓取完整 Profile + Tweets。"""

# TODO: 实现深度抓取逻辑
# 1. 从候选队列读取 AI 过滤通过的创作者
# 2. 批量触发 Apify Deep Scrape Actor (每批 50 人)
# 3. 使用 Residential Proxy
# 4. 数据回写: creators 表更新 profile, tweets 表写入推文
