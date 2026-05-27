-- Migration 010: 删除 model_evaluations 表中的 sps_threshold 列
-- 该列已不在代码中使用，属于历史遗留字段

ALTER TABLE model_evaluations DROP COLUMN IF EXISTS sps_threshold;
