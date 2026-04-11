-- 双模型评分字段（资格模型 + 销量预测模型）
-- 保持向后兼容：保留 creator_scores.sps_score 作为预测销量评分主分

ALTER TABLE creator_scores
  ADD COLUMN IF NOT EXISTS sellability_score FLOAT,
  ADD COLUMN IF NOT EXISTS is_sellable BOOLEAN,
  ADD COLUMN IF NOT EXISTS predicted_sales FLOAT;

CREATE INDEX IF NOT EXISTS idx_scores_sellability ON creator_scores(sellability_score DESC);
CREATE INDEX IF NOT EXISTS idx_scores_is_sellable ON creator_scores(is_sellable);
