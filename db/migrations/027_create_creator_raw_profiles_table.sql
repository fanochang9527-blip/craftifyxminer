-- 027: 创建 creator_raw_profiles 表，独立存储完整 Apify profile 原始 JSON
-- 避免在 creators 主表上增加大体积 JSONB 字段导致主表膨胀

CREATE TABLE IF NOT EXISTS creator_raw_profiles (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
    source VARCHAR(50) NOT NULL,
    raw_profile JSONB NOT NULL,
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(creator_id, source)
);

CREATE INDEX IF NOT EXISTS idx_creator_raw_profiles_creator
    ON creator_raw_profiles (creator_id);
CREATE INDEX IF NOT EXISTS idx_creator_raw_profiles_source
    ON creator_raw_profiles (source);

COMMENT ON TABLE creator_raw_profiles IS '创作者原始 profile 数据表：存储各来源抓取到的完整 Apify profile JSON，避免 creators 主表膨胀';
COMMENT ON COLUMN creator_raw_profiles.creator_id IS '关联创作者 ID（外键）';
COMMENT ON COLUMN creator_raw_profiles.source IS '数据来源：intake / deep_scrape / dna / follower_refresh';
COMMENT ON COLUMN creator_raw_profiles.raw_profile IS 'Apify 返回的完整创作者 profile 原始 JSON';
COMMENT ON COLUMN creator_raw_profiles.collected_at IS '数据采集时间';
