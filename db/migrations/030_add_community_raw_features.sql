-- 新增社区活跃度原始特征，替代可卖货模型中的 community_score
ALTER TABLE creator_features
    ADD COLUMN IF NOT EXISTS mention_rate FLOAT,
    ADD COLUMN IF NOT EXISTS retweet_rate FLOAT;

COMMENT ON COLUMN creator_features.mention_rate IS '提及互动率：含 @ mention 的推文占比（来源：feature_engine.calc_mention_rate）';
COMMENT ON COLUMN creator_features.retweet_rate IS '平均转发数：单条推文的平均 retweets（来源：feature_engine.calc_retweet_rate）';
