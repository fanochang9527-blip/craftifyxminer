-- 025_project_features_enum_refactor.sql
-- 项目级销量预测特征重构：
-- 1. 项目枚举特征 domain / product_attribute 保留为 TEXT，由模型端单值整数编码；
-- 2. 市场层级由三个布尔列合并为单个 creator_market_tier TEXT 枚举列；
-- 3. 删除已停用或废弃的作者侧特征列。

BEGIN;

-- 新增创作者市场层级枚举列
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS creator_market_tier TEXT;

-- 从旧布尔列迁移数据（优先 high，其次 mid，否则 low；兼容 NULL）
UPDATE projects
SET creator_market_tier = CASE
    WHEN creator_market_tier_high IS TRUE THEN 'high'
    WHEN creator_market_tier_mid IS TRUE THEN 'mid'
    WHEN creator_market_tier_low IS TRUE THEN 'low'
    ELSE 'low'
END
WHERE creator_market_tier IS NULL;

-- 删除旧的市场层级布尔列
ALTER TABLE projects
    DROP COLUMN IF EXISTS creator_market_tier_high,
    DROP COLUMN IF EXISTS creator_market_tier_mid,
    DROP COLUMN IF EXISTS creator_market_tier_low;

-- 删除已停用/废弃的作者侧特征列
ALTER TABLE projects
    DROP COLUMN IF EXISTS creator_avg_daily_posts_30d,
    DROP COLUMN IF EXISTS creator_reply_engagement_rate,
    DROP COLUMN IF EXISTS creator_content_furry,
    DROP COLUMN IF EXISTS creator_content_anime,
    DROP COLUMN IF EXISTS creator_content_vtuber,
    DROP COLUMN IF EXISTS creator_content_gaming,
    DROP COLUMN IF EXISTS creator_content_webcomic,
    DROP COLUMN IF EXISTS creator_content_bl,
    DROP COLUMN IF EXISTS creator_content_gl,
    DROP COLUMN IF EXISTS creator_content_nsfw;

COMMIT;
