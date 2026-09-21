-- 临时实验：为项目级销量预测模型增加创作者国家特征
-- 数据来自 Apify 抓取的 X profile location 字段，经规则解析到国家级别
-- 注意：location 为创作者手动填写，可能存在错误/虚假/为空的情况，需经 AB 测试验证后再决定是否正式入模

ALTER TABLE projects ADD COLUMN IF NOT EXISTS creator_country TEXT;

COMMENT ON COLUMN projects.creator_country IS '从 X profile location 解析出的国家（实验特征），用于项目级销量预测模型 AB 测试';
