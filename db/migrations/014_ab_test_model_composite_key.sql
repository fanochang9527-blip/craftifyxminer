-- Migration 014: 支持 AB 测试 — 同一创作者可存多个模型的分析结果
-- 将 creator_id 的单列 UNIQUE 改为 (creator_id, model_used) 组合 UNIQUE

ALTER TABLE creator_content_analysis
    DROP CONSTRAINT IF EXISTS creator_content_analysis_creator_id_key;

ALTER TABLE creator_content_analysis
    ADD CONSTRAINT creator_content_analysis_creator_model_key
    UNIQUE (creator_id, model_used);
