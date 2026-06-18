-- SPS 模型 DNA 特征列扩展
-- 这些字段由 pipeline/creator_dna.py 写入，供 SPS 模型（Lasso）训练与预测

ALTER TABLE creator_features
    ADD COLUMN IF NOT EXISTS followers_log FLOAT,
    ADD COLUMN IF NOT EXISTS following_follower_ratio FLOAT,
    ADD COLUMN IF NOT EXISTS avg_daily_posts_30d FLOAT,
    ADD COLUMN IF NOT EXISTS reply_engagement_rate FLOAT,
    ADD COLUMN IF NOT EXISTS account_age_days_log FLOAT,
    ADD COLUMN IF NOT EXISTS has_shop_link FLOAT,
    ADD COLUMN IF NOT EXISTS is_nsfw FLOAT,
    ADD COLUMN IF NOT EXISTS is_multi_platform FLOAT,
    ADD COLUMN IF NOT EXISTS market_tier_high FLOAT,
    ADD COLUMN IF NOT EXISTS market_tier_mid FLOAT,
    ADD COLUMN IF NOT EXISTS market_tier_low FLOAT,
    ADD COLUMN IF NOT EXISTS species_type_human FLOAT,
    ADD COLUMN IF NOT EXISTS species_type_anthro FLOAT,
    ADD COLUMN IF NOT EXISTS species_type_animal FLOAT,
    ADD COLUMN IF NOT EXISTS species_type_fantasy FLOAT;

COMMENT ON COLUMN creator_features.followers_log IS '粉丝数 log1p，DNA 原始特征';
COMMENT ON COLUMN creator_features.following_follower_ratio IS '关注/粉丝比，DNA 原始特征';
COMMENT ON COLUMN creator_features.avg_daily_posts_30d IS '近 30 天日均发帖数，DNA 原始特征';
COMMENT ON COLUMN creator_features.reply_engagement_rate IS '回复互动率，DNA 原始特征';
COMMENT ON COLUMN creator_features.account_age_days_log IS '账号年龄 log1p，DNA 原始特征';
COMMENT ON COLUMN creator_features.has_shop_link IS '是否有店铺链接，DNA 商业信号';
COMMENT ON COLUMN creator_features.is_nsfw IS '是否 NSFW，DNA 商业信号';
COMMENT ON COLUMN creator_features.is_multi_platform IS '是否多平台，DNA 商业信号';
COMMENT ON COLUMN creator_features.market_tier_high IS '高购买力市场 one-hot';
COMMENT ON COLUMN creator_features.market_tier_mid IS '中等购买力市场 one-hot';
COMMENT ON COLUMN creator_features.market_tier_low IS '低购买力市场 one-hot';
COMMENT ON COLUMN creator_features.species_type_human IS '形象：人类 one-hot';
COMMENT ON COLUMN creator_features.species_type_anthro IS '形象：兽人/拟人 one-hot';
COMMENT ON COLUMN creator_features.species_type_animal IS '形象：纯动物 one-hot';
COMMENT ON COLUMN creator_features.species_type_fantasy IS '形象：奇幻生物 one-hot';
