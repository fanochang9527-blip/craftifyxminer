-- Migration 009: 清理 model_evaluations 表结构
-- 1. 调整 model_name 列到 id 之后
-- 2. 删除 model_algorithm、pearson_corr、mape 列
-- PostgreSQL 不支持直接移动列，采用备份-重建-恢复策略

BEGIN;

-- 1. 备份现有数据
CREATE TABLE model_evaluations_backup AS SELECT * FROM model_evaluations;

-- 2. 创建新表（正确列顺序，不含被删列）
CREATE TABLE model_evaluations_new (
    id INTEGER PRIMARY KEY,
    model_name VARCHAR(20),
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

-- 3. 迁移数据（只保留需要的列）
INSERT INTO model_evaluations_new (
    id, model_name, evaluated_at, model_version, n_seeds, n_predictions,
    n_bd_reviewed, n_interested, n_rejected, recall, precision_score,
    f2_score, precision_at_250, spearman_corr, r2, mae, sps_threshold, notes
)
SELECT
    id, model_name, evaluated_at, model_version, n_seeds, n_predictions,
    n_bd_reviewed, n_interested, n_rejected, recall, precision_score,
    f2_score, precision_at_250, spearman_corr, r2, mae, sps_threshold, notes
FROM model_evaluations;

-- 4. 关联已有序列到新表
SELECT setval('model_evaluations_id_seq', COALESCE((SELECT MAX(id) FROM model_evaluations_new), 0) + 1, false);
ALTER TABLE model_evaluations_new ALTER COLUMN id SET DEFAULT nextval('model_evaluations_id_seq');
ALTER SEQUENCE model_evaluations_id_seq OWNED BY model_evaluations_new.id;

-- 5. 删除旧表，重命名新表
DROP TABLE model_evaluations;
ALTER TABLE model_evaluations_new RENAME TO model_evaluations;

-- 6. 清理备份
DROP TABLE model_evaluations_backup;

COMMIT;
