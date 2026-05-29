-- Migration 012: 为 ML V2 实验组新增原始特征列
-- creator_features 表新增 5 维拆分特征，用于替代组合特征喂给模型

ALTER TABLE creator_features
    ADD COLUMN IF NOT EXISTS social_engagement_rate FLOAT,
    ADD COLUMN IF NOT EXISTS conversation_rate FLOAT,
    ADD COLUMN IF NOT EXISTS fanart_ratio FLOAT,
    ADD COLUMN IF NOT EXISTS virality_raw_ratio FLOAT,
    ADD COLUMN IF NOT EXISTS monthly_engagement_base FLOAT;
