-- 将创作者 DNA 从物种分类改为内容分类
-- 8 个选项：furry / anime / vtuber / gaming / webcomic / bl / gl / nsfw

-- creators_detail: 删除物种分类列，新增内容分类列
ALTER TABLE creators_detail
    DROP COLUMN IF EXISTS species_type_human,
    DROP COLUMN IF EXISTS species_type_anthro,
    DROP COLUMN IF EXISTS species_type_animal,
    DROP COLUMN IF EXISTS species_type_fantasy,
    DROP COLUMN IF EXISTS species_type_robot,
    DROP COLUMN IF EXISTS species_type_mixed;

ALTER TABLE creators_detail
    ADD COLUMN IF NOT EXISTS content_furry BOOLEAN,
    ADD COLUMN IF NOT EXISTS content_anime BOOLEAN,
    ADD COLUMN IF NOT EXISTS content_vtuber BOOLEAN,
    ADD COLUMN IF NOT EXISTS content_gaming BOOLEAN,
    ADD COLUMN IF NOT EXISTS content_webcomic BOOLEAN,
    ADD COLUMN IF NOT EXISTS content_bl BOOLEAN,
    ADD COLUMN IF NOT EXISTS content_gl BOOLEAN,
    ADD COLUMN IF NOT EXISTS content_nsfw BOOLEAN,
    ADD COLUMN IF NOT EXISTS content_classifications TEXT[];

-- creator_features: 删除物种分类列，新增内容分类列
ALTER TABLE creator_features
    DROP COLUMN IF EXISTS species_type_human,
    DROP COLUMN IF EXISTS species_type_anthro,
    DROP COLUMN IF EXISTS species_type_animal,
    DROP COLUMN IF EXISTS species_type_fantasy,
    DROP COLUMN IF EXISTS species_type_mixed;

ALTER TABLE creator_features
    ADD COLUMN IF NOT EXISTS content_furry FLOAT,
    ADD COLUMN IF NOT EXISTS content_anime FLOAT,
    ADD COLUMN IF NOT EXISTS content_vtuber FLOAT,
    ADD COLUMN IF NOT EXISTS content_gaming FLOAT,
    ADD COLUMN IF NOT EXISTS content_webcomic FLOAT,
    ADD COLUMN IF NOT EXISTS content_bl FLOAT,
    ADD COLUMN IF NOT EXISTS content_gl FLOAT,
    ADD COLUMN IF NOT EXISTS content_nsfw FLOAT;

COMMENT ON COLUMN creators_detail.content_furry IS '内容分类：Furry';
COMMENT ON COLUMN creators_detail.content_anime IS '内容分类：Anime';
COMMENT ON COLUMN creators_detail.content_vtuber IS '内容分类：VTuber';
COMMENT ON COLUMN creators_detail.content_gaming IS '内容分类：Gaming';
COMMENT ON COLUMN creators_detail.content_webcomic IS '内容分类：Webcomic';
COMMENT ON COLUMN creators_detail.content_bl IS '内容分类：BL';
COMMENT ON COLUMN creators_detail.content_gl IS '内容分类：GL';
COMMENT ON COLUMN creators_detail.content_nsfw IS '内容分类：NSFW';
COMMENT ON COLUMN creators_detail.content_classifications IS '内容分类数组（最多 3 个）';
