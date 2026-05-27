-- Migration 008: 模型评价表重构 — 支持双模型独立评价
-- 新增 model_name、model_algorithm、pearson_corr、mape 字段
-- 兼容历史数据：旧记录的 model_name 留空，由业务层按需处理

ALTER TABLE model_evaluations
    ADD COLUMN IF NOT EXISTS model_name VARCHAR(20),
    ADD COLUMN IF NOT EXISTS model_algorithm VARCHAR(50),
    ADD COLUMN IF NOT EXISTS pearson_corr FLOAT,
    ADD COLUMN IF NOT EXISTS mape FLOAT;

-- 旧数据只有一行混合记录，不强行拆分；后续 evaluate_model 会写入独立两行
