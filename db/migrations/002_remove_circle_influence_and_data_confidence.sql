-- Migration: 从 creator_features 移除 circle_influence_score 和 data_confidence
-- 原因：业务决策去除这两个特征维度

ALTER TABLE creator_features
    DROP COLUMN IF EXISTS circle_influence_score,
    DROP COLUMN IF EXISTS data_confidence;
