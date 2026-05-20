-- Migration: 新增 audience_segment_score（第 9 维特征）+ creator_segment 分类标签
-- Applied: 2026-05-19

-- 1. creators 表新增分类标签
ALTER TABLE creators
    ADD COLUMN IF NOT EXISTS creator_segment VARCHAR(20);

-- 2. creator_features 表新增第 9 维数值特征
ALTER TABLE creator_features
    ADD COLUMN IF NOT EXISTS audience_segment_score FLOAT;

-- 3. 存量数据 backfill（基于现有 bio / website / username）

-- 3.1 先给 creators 表做 creator_segment 标记
UPDATE creators
SET creator_segment = 'nsfw'
WHERE creator_segment IS NULL
  AND (
      lower(coalesce(bio, '')) LIKE '%nsfw%'
      OR coalesce(bio, '') LIKE '%🔞%'
      OR lower(coalesce(username, '')) LIKE '%nsfw%'
      OR coalesce(username, '') LIKE '%🔞%'
  );

UPDATE creators
SET creator_segment = 'multi_platform'
WHERE creator_segment IS NULL
  AND (
      lower(coalesce(bio, '') || ' ' || coalesce(website, ''))
      LIKE ANY(ARRAY[
          '%instagram.com%', '%twitch.tv%', '%youtube.com%', '%pixiv.net%',
          '%booth.pm%', '%etsy.com%', '%patreon.com%', '%fanbox.cc%',
          '%skeb.jp%', '%artstation.com%', '%tiktok.com%', '%linkedin.com%',
          '%behance.net%', '%discord.gg%', '%reddit.com%', '%carrd.co%',
          '%ko-fi.com%', '%buy me a coffee%', '%linktr.ee%', '%lit.link%',
          '%taplink.cc%', '%toyhou.se%', '%newgrounds.com%', '%furaffinity.net%'
      ])
  );

UPDATE creators
SET creator_segment = 'mainstream'
WHERE creator_segment IS NULL;

-- 3.2 给已有 creator_features 的存量记录补算 audience_segment_score
UPDATE creator_features cf
SET audience_segment_score = CASE c.creator_segment
    WHEN 'multi_platform' THEN 80.0
    WHEN 'nsfw'           THEN 20.0
    ELSE                       50.0
END
FROM creators c
WHERE cf.creator_id = c.id
  AND cf.audience_segment_score IS NULL;
