-- 创作者 DNA 字段扩展
-- 将 DNA 分析结果存入 creators_detail，供前端展示与 SPS 模型输入

ALTER TABLE creators_detail
    ADD COLUMN IF NOT EXISTS market_tier_high BOOLEAN,
    ADD COLUMN IF NOT EXISTS market_tier_mid BOOLEAN,
    ADD COLUMN IF NOT EXISTS market_tier_low BOOLEAN,
    ADD COLUMN IF NOT EXISTS has_shop_link BOOLEAN,
    ADD COLUMN IF NOT EXISTS shop_platforms TEXT[],
    ADD COLUMN IF NOT EXISTS is_nsfw BOOLEAN,
    ADD COLUMN IF NOT EXISTS is_multi_platform BOOLEAN,
    ADD COLUMN IF NOT EXISTS following_follower_ratio FLOAT,
    ADD COLUMN IF NOT EXISTS avg_daily_posts_30d FLOAT,
    ADD COLUMN IF NOT EXISTS reply_engagement_rate FLOAT,
    ADD COLUMN IF NOT EXISTS account_age_days_log FLOAT,
    ADD COLUMN IF NOT EXISTS species_type_human BOOLEAN,
    ADD COLUMN IF NOT EXISTS species_type_anthro BOOLEAN,
    ADD COLUMN IF NOT EXISTS species_type_animal BOOLEAN,
    ADD COLUMN IF NOT EXISTS species_type_fantasy BOOLEAN,
    ADD COLUMN IF NOT EXISTS species_type_robot BOOLEAN,
    ADD COLUMN IF NOT EXISTS species_type_mixed BOOLEAN,
    ADD COLUMN IF NOT EXISTS style_tags TEXT[],
    ADD COLUMN IF NOT EXISTS theme_tags TEXT[],
    ADD COLUMN IF NOT EXISTS raw_dna_analysis JSONB;

COMMENT ON COLUMN creators_detail.market_tier_high IS '高购买力市场 one-hot';
COMMENT ON COLUMN creators_detail.market_tier_mid IS '中等购买力市场 one-hot';
COMMENT ON COLUMN creators_detail.market_tier_low IS '低购买力市场 one-hot';
COMMENT ON COLUMN creators_detail.has_shop_link IS '是否有店铺/商品链接';
COMMENT ON COLUMN creators_detail.shop_platforms IS '店铺平台列表，如 [booth, etsy, patreon]';
COMMENT ON COLUMN creators_detail.is_nsfw IS '是否为成人向内容';
COMMENT ON COLUMN creators_detail.is_multi_platform IS '是否有多平台链接';
COMMENT ON COLUMN creators_detail.following_follower_ratio IS '关注/粉丝比';
COMMENT ON COLUMN creators_detail.avg_daily_posts_30d IS '近 30 天日均发帖数';
COMMENT ON COLUMN creators_detail.reply_engagement_rate IS '回复互动率';
COMMENT ON COLUMN creators_detail.account_age_days_log IS '账号年龄 log1p';
COMMENT ON COLUMN creators_detail.species_type_human IS '形象一级分类：人类';
COMMENT ON COLUMN creators_detail.species_type_anthro IS '形象一级分类：兽人/拟人';
COMMENT ON COLUMN creators_detail.species_type_animal IS '形象一级分类：纯动物';
COMMENT ON COLUMN creators_detail.species_type_fantasy IS '形象一级分类：奇幻生物';
COMMENT ON COLUMN creators_detail.species_type_robot IS '形象一级分类：机械/机甲';
COMMENT ON COLUMN creators_detail.species_type_mixed IS '形象一级分类：混合/无法归类';
COMMENT ON COLUMN creators_detail.style_tags IS '视觉风格标签，如 [chibi, anime]';
COMMENT ON COLUMN creators_detail.theme_tags IS '主题标签，如 [cute, horror]';
COMMENT ON COLUMN creators_detail.raw_dna_analysis IS 'LLM DNA 分析原始输出 JSON';
