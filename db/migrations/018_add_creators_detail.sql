-- Migration 018: 新增 creators_detail 高价值创作者详情档案表
-- 仅收录 is_seed=true 或 bd_decision='interested' 的创作者

CREATE TABLE IF NOT EXISTS creators_detail (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) ON DELETE CASCADE UNIQUE,
    is_seed BOOLEAN DEFAULT false,
    bd_decision VARCHAR(20),
    display_name TEXT,
    profile_image_url TEXT,
    banner_image_url TEXT,
    verified BOOLEAN,
    location TEXT,
    country TEXT,
    region TEXT,
    timezone TEXT,
    followers INTEGER,
    following INTEGER,
    tweets_count INTEGER,
    listed_count INTEGER,
    account_age_days INTEGER,
    platform_created_at TIMESTAMP,
    tags TEXT[],
    creator_type_tags TEXT[],
    website TEXT,
    website_links TEXT[],
    email TEXT,
    commission_status VARCHAR(50),
    merch_links TEXT[],
    social_links JSONB,
    raw_profile JSONB,
    first_synced_at TIMESTAMP DEFAULT NOW(),
    last_synced_at TIMESTAMP DEFAULT NOW(),
    sync_source VARCHAR(50)
);

COMMENT ON TABLE creators_detail IS '高价值创作者详情档案表：仅收录种子创作者或 BD 判定为 interested 的创作者，集中存储地区、标签、链接等精细化运营所需的详细字段';
COMMENT ON COLUMN creators_detail.creator_id IS '关联创作者 ID（外键，唯一）';
COMMENT ON COLUMN creators_detail.is_seed IS '是否为种子创作者';
COMMENT ON COLUMN creators_detail.bd_decision IS 'BD 最终决策（interested / rejected_unfit / rejected_not_creator）';
COMMENT ON COLUMN creators_detail.display_name IS '平台显示名称';
COMMENT ON COLUMN creators_detail.profile_image_url IS '头像图片 URL';
COMMENT ON COLUMN creators_detail.banner_image_url IS '横幅/背景图 URL';
COMMENT ON COLUMN creators_detail.verified IS '是否平台认证';
COMMENT ON COLUMN creators_detail.location IS '用户填写的地理位置（如 Tokyo / Los Angeles, CA）';
COMMENT ON COLUMN creators_detail.country IS '推断或原始的国家';
COMMENT ON COLUMN creators_detail.region IS '地区/州/省';
COMMENT ON COLUMN creators_detail.timezone IS '时区';
COMMENT ON COLUMN creators_detail.followers IS '粉丝数';
COMMENT ON COLUMN creators_detail.following IS '关注数';
COMMENT ON COLUMN creators_detail.tweets_count IS '推文/发帖总数';
COMMENT ON COLUMN creators_detail.listed_count IS '被加入列表数（Twitter 原字段）';
COMMENT ON COLUMN creators_detail.account_age_days IS '账号年龄（天）';
COMMENT ON COLUMN creators_detail.platform_created_at IS '平台账号注册时间';
COMMENT ON COLUMN creators_detail.tags IS '作品与业务标签（如 ["OC", "fanart", "VTuber"]）';
COMMENT ON COLUMN creators_detail.creator_type_tags IS '创作者类型标签（如 ["oc_creator", "vtuber"]）';
COMMENT ON COLUMN creators_detail.website IS '主页链接';
COMMENT ON COLUMN creators_detail.website_links IS '从 bio 解析出的所有链接';
COMMENT ON COLUMN creators_detail.email IS '联系邮箱';
COMMENT ON COLUMN creators_detail.commission_status IS '接稿状态（如 open / closed / waitlist）';
COMMENT ON COLUMN creators_detail.merch_links IS '商品/店铺链接';
COMMENT ON COLUMN creators_detail.social_links IS '其他社交平台链接 JSONB（如 Instagram/Pixiv/YouTube 等）';
COMMENT ON COLUMN creators_detail.raw_profile IS '平台原始 Profile JSON，便于后续提取新字段';
COMMENT ON COLUMN creators_detail.first_synced_at IS '首次同步时间';
COMMENT ON COLUMN creators_detail.last_synced_at IS '最后同步时间';
COMMENT ON COLUMN creators_detail.sync_source IS '同步来源（如 deep_scrape / seed_import / bd_decision / backfill）';

CREATE INDEX IF NOT EXISTS idx_creators_detail_country ON creators_detail (country);
CREATE INDEX IF NOT EXISTS idx_creators_detail_tags ON creators_detail USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_creators_detail_type_tags ON creators_detail USING GIN (creator_type_tags);
CREATE INDEX IF NOT EXISTS idx_creators_detail_last_synced ON creators_detail (last_synced_at);

-- 初始同步：将当前符合条件的创作者（is_seed=true 或 bd_decision='interested'）写入基础记录
INSERT INTO creators_detail (creator_id, is_seed, bd_decision, sync_source)
SELECT id, is_seed, bd_decision, 'migration_018'
FROM creators
WHERE is_seed = true OR bd_decision = 'interested'
ON CONFLICT (creator_id) DO UPDATE SET
    is_seed = EXCLUDED.is_seed,
    bd_decision = EXCLUDED.bd_decision,
    last_synced_at = NOW();
