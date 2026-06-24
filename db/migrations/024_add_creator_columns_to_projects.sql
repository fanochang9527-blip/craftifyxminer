-- 项目表扩展：直接存放作者/创作者特征字段（每行一个项目）

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS x_link TEXT,
    ADD COLUMN IF NOT EXISTS ad_link_raw TEXT,
    ADD COLUMN IF NOT EXISTS creator_username TEXT,
    ADD COLUMN IF NOT EXISTS creator_followers FLOAT,
    ADD COLUMN IF NOT EXISTS creator_following FLOAT,
    ADD COLUMN IF NOT EXISTS creator_tweets_count FLOAT,
    ADD COLUMN IF NOT EXISTS creator_bio TEXT,
    ADD COLUMN IF NOT EXISTS creator_followers_log FLOAT,
    ADD COLUMN IF NOT EXISTS creator_following_follower_ratio FLOAT,
    ADD COLUMN IF NOT EXISTS creator_avg_daily_posts_30d FLOAT,
    ADD COLUMN IF NOT EXISTS creator_reply_engagement_rate FLOAT,
    ADD COLUMN IF NOT EXISTS creator_account_age_days_log FLOAT,
    ADD COLUMN IF NOT EXISTS creator_has_shop_link BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_is_nsfw BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_is_multi_platform BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_market_tier_high BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_market_tier_mid BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_market_tier_low BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_content_furry BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_content_anime BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_content_vtuber BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_content_gaming BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_content_webcomic BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_content_bl BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_content_gl BOOLEAN,
    ADD COLUMN IF NOT EXISTS creator_content_nsfw BOOLEAN;

COMMENT ON COLUMN projects.x_link IS '用于 Apify 采集的 X/Twitter 主链接（取 汇总.xlsx 中第一个 X 链接）';
COMMENT ON COLUMN projects.ad_link_raw IS '汇总.xlsx 中原始的创作者推荐链接（含多平台）';
COMMENT ON COLUMN projects.creator_username IS '创作者 X 平台用户名';
COMMENT ON COLUMN projects.creator_is_multi_platform IS '汇总.xlsx 中该项目是否包含多个平台链接（创作者相关特征）';

CREATE INDEX IF NOT EXISTS idx_projects_x_link ON projects (x_link);
CREATE INDEX IF NOT EXISTS idx_projects_creator_username ON projects (creator_username);
