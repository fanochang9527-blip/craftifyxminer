-- Migration 017: 为 creator_features 添加 growth_is_real 转正标记字段
-- 用于区分 growth_score 是占位值（50.0）还是基于真实历史快照计算得出

-- 1. 新增字段
ALTER TABLE creator_features
    ADD COLUMN IF NOT EXISTS growth_is_real BOOLEAN DEFAULT false;

-- 2. 存量数据 backfill：已转正的创作者（growth_score 不为 NULL 且不为 50.0）
UPDATE creator_features
SET growth_is_real = true
WHERE growth_score IS NOT NULL
  AND growth_score != 50.0;
