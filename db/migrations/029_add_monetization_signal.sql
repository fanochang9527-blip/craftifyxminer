-- 新增高置信变现/店铺链接布尔特征，替代可卖货模型中的 monetization_score
ALTER TABLE creator_features
    ADD COLUMN IF NOT EXISTS has_monetization_signal BOOLEAN DEFAULT false;

COMMENT ON COLUMN creator_features.has_monetization_signal IS '高置信变现/店铺链接信号：bio/website 中出现 Level 1 Link DNA 店铺平台时为 true（来源：feature_engine.calc_monetization_signal）';
