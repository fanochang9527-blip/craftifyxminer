"""SPS 评分 + 中心度分层。"""

# TODO: 实现 SPS 评分
# 1. 加载 config/weights.yaml
# 2. 根据 creator_type 选择权重向量
# 3. SPS = sum(weight_i * score_i) for 10 dimensions
# 4. 中心度: SQL 查 creator_graph 被多少 Seed 关注 -> Hub(>=5) / Connector(2-4) / Peripheral(0-1)
# 5. Contact Probability: 初版 SPS*0.8 + Monetization*0.2
# 6. 写入 creator_scores 表
