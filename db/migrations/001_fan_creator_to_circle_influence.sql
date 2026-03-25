-- Miner 7.0：用「圈层影响力」字段 circle_influence_score 替代 fan_creator_ratio。
-- 新库请直接使用 db/schema.sql，无需执行本迁移。
-- 仅当 creator_features 仍含 fan_creator_ratio 时执行。

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'creator_features'
      AND column_name = 'fan_creator_ratio'
  ) THEN
    ALTER TABLE creator_features
      RENAME COLUMN fan_creator_ratio TO circle_influence_score;
  END IF;
END $$;
