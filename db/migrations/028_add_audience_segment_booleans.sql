-- 新增受众分段布尔特征，替代可卖货模型中的 audience_segment_score
ALTER TABLE creator_features
    ADD COLUMN IF NOT EXISTS audience_is_nsfw BOOLEAN,
    ADD COLUMN IF NOT EXISTS audience_is_multi_platform BOOLEAN;

COMMENT ON COLUMN creator_features.audience_is_nsfw IS '受众分段：是否为成人向/NSFW 创作者（来源：feature_engine.calc_audience_segment_booleans）';
COMMENT ON COLUMN creator_features.audience_is_multi_platform IS '受众分段：是否在 bio/website 中露出多平台链接（来源：feature_engine.calc_audience_segment_booleans）';
