-- 026: 在 tweets 表增加 Apify 原始 tweet 数据及转发类型字段
-- 为后续模型特征输入重构保留一手数据

ALTER TABLE tweets
    ADD COLUMN IF NOT EXISTS is_retweet BOOLEAN,
    ADD COLUMN IF NOT EXISTS is_quote BOOLEAN,
    ADD COLUMN IF NOT EXISTS is_reply BOOLEAN,
    ADD COLUMN IF NOT EXISTS quoted_tweet_id TEXT,
    ADD COLUMN IF NOT EXISTS raw_tweet JSONB;

COMMENT ON COLUMN tweets.is_retweet IS '是否为纯转发（retweet）';
COMMENT ON COLUMN tweets.is_quote IS '是否为引用转发（quote tweet）';
COMMENT ON COLUMN tweets.is_reply IS '是否为回复';
COMMENT ON COLUMN tweets.quoted_tweet_id IS '被引用的原推文 ID';
COMMENT ON COLUMN tweets.raw_tweet IS 'Apify 返回的完整 tweet 原始 JSON';
