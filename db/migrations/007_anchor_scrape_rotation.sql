-- 锚点扫描轮换机制：记录每个锚点最后一次被扫描的时间

ALTER TABLE creators
    ADD COLUMN IF NOT EXISTS last_scraped_as_anchor TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_creators_last_scraped_anchor
    ON creators(last_scraped_as_anchor);
