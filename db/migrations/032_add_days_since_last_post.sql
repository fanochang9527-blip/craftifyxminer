-- 为 sellability 模型新增最近发帖时间特征列
ALTER TABLE creator_features ADD COLUMN IF NOT EXISTS days_since_last_post FLOAT;

COMMENT ON COLUMN creator_features.days_since_last_post IS
    '最近发帖距今天数：越小表示创作者越活跃，无推文时按 365 天计（来源：feature_engine.calc_days_since_last_post）';
