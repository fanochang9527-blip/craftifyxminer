-- Migration 013: 多模态内容风格过滤
-- 1. tweets 表新增 media_types 字段（标记 photo / video / animated_gif）
-- 2. 新增 creator_content_analysis 表（存储多模态 LLM 分析结果）

ALTER TABLE tweets ADD COLUMN IF NOT EXISTS media_types TEXT[];

CREATE TABLE IF NOT EXISTS creator_content_analysis (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) UNIQUE,
    is_realistic BOOLEAN,
    has_fixed_ip BOOLEAN,
    confidence FLOAT,
    model_used VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',
    analyzed_at TIMESTAMP DEFAULT NOW(),
    raw_result JSONB,
    media_sample TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_content_analysis_status ON creator_content_analysis (status);
CREATE INDEX IF NOT EXISTS idx_content_analysis_model ON creator_content_analysis (model_used);
