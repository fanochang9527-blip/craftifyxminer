"""10 维指标计算引擎 — 基于 Profile + Tweets 数据计算创作者特征。"""

# TODO: 实现 10 维指标计算
# Audience:              min(log10(followers+1) * 20, 100)
# Engagement:            min((avg_likes + avg_rt*2 + avg_replies*3) / followers * 100, 100)
# Virality:              min(top3_avg / monthly_avg, 10) * 10
# Posting:               min(monthly_posts / 30 * 100, 100)
# Monetization:          复用 bio_rules.yaml 中的 Link DNA + 动作关键词
# Growth:                月环比粉丝增长 (初版 0.5 占位)
# Fan Creator Ratio:     粉丝中创作者占比 (初版 0.5 占位)
# Character Consistency: 推文图片 URL 域名集中度 (初版简化)
# Community:             min((mentions*2 + fanart*5) / max_community * 100, 100)
# Data Confidence:       min(account_age*0.6 + completeness*0.4, 1.0) * 100
