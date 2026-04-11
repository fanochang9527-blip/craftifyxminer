-- Migration 004: SPS ML 重构
-- 废弃 seed_tier，新增 creator_type 双字段，新建 model_evaluations 表

-- 1. 废弃 seed_tier
ALTER TABLE creators DROP COLUMN IF EXISTS seed_tier;

-- 2. 创作者类型：人工标注 + 机器分类，双字段并存
ALTER TABLE creators ADD COLUMN IF NOT EXISTS creator_type_manual VARCHAR(20);
ALTER TABLE creators ADD COLUMN IF NOT EXISTS creator_type_auto VARCHAR(20);

-- 3. 模型评估表
CREATE TABLE IF NOT EXISTS model_evaluations (
    id SERIAL PRIMARY KEY,
    evaluated_at TIMESTAMP DEFAULT NOW(),
    model_version TEXT,
    n_seeds INTEGER,
    n_predictions INTEGER,
    n_bd_reviewed INTEGER,
    n_interested INTEGER,
    n_rejected INTEGER,
    recall FLOAT,
    precision_score FLOAT,
    f2_score FLOAT,
    precision_at_250 FLOAT,
    spearman_corr FLOAT,
    r2 FLOAT,
    mae FLOAT,
    sps_threshold FLOAT,
    notes TEXT
);
