-- 种子/创作者唯一键：(platform, platform_account_id)
-- 多行合作销售记录导入时，应用层按成交笔数优先、销售额次之去重后再写入。

ALTER TABLE creators ADD COLUMN IF NOT EXISTS platform VARCHAR(64) NOT NULL DEFAULT 'twitter';
ALTER TABLE creators ADD COLUMN IF NOT EXISTS platform_account_id TEXT;
ALTER TABLE creators ADD COLUMN IF NOT EXISTS sales_transaction_count INTEGER DEFAULT 0;

UPDATE creators SET platform_account_id = LOWER(TRIM(username)) WHERE platform_account_id IS NULL;

ALTER TABLE creators ALTER COLUMN platform_account_id SET NOT NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'creators_username_key' AND conrelid = 'creators'::regclass
  ) THEN
    ALTER TABLE creators DROP CONSTRAINT creators_username_key;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_creators_platform_account_id
  ON creators(platform, platform_account_id);
