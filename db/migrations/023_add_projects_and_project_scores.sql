-- 项目级销量预测：新增 projects 与 project_scores 表

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) ON DELETE SET NULL,
    sku TEXT UNIQUE,
    domain TEXT,
    product_attribute TEXT,
    price FLOAT,
    order_quantity FLOAT NOT NULL,
    ad_link TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE projects IS '项目/合作级样本表：单次合作项目的销量、特征与创作者关联';
COMMENT ON COLUMN projects.project_id IS '系统生成的项目唯一编号';
COMMENT ON COLUMN projects.creator_id IS '关联创作者 ID（通过 ad_link 与 creators.website 匹配）';
COMMENT ON COLUMN projects.sku IS '外部打样编号，用于与外部系统对接';
COMMENT ON COLUMN projects.domain IS '项目领域（枚举特征）';
COMMENT ON COLUMN projects.product_attribute IS '产品属性（枚举特征）';
COMMENT ON COLUMN projects.price IS '项目定价（USD）';
COMMENT ON COLUMN projects.order_quantity IS '订单产品数量，项目级模型预测目标 y';
COMMENT ON COLUMN projects.ad_link IS '创作者推荐链接（命中 seed 白名单后拼接）';
COMMENT ON COLUMN projects.metadata IS '扩展字段 JSONB，用于后续增加列';

CREATE INDEX IF NOT EXISTS idx_projects_creator_id ON projects (creator_id);
CREATE INDEX IF NOT EXISTS idx_projects_domain ON projects (domain);
CREATE INDEX IF NOT EXISTS idx_projects_product_attribute ON projects (product_attribute);


CREATE TABLE IF NOT EXISTS project_scores (
    id SERIAL PRIMARY KEY,
    project_id TEXT REFERENCES projects(project_id) ON DELETE CASCADE,
    creator_id INTEGER REFERENCES creators(id) ON DELETE SET NULL,
    predicted_sales FLOAT,
    sps_score FLOAT,
    confidence FLOAT,
    contact_probability FLOAT,
    predicted_response_rate FLOAT,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(project_id)
);

COMMENT ON TABLE project_scores IS '项目级销量预测结果表：每个项目的预测销量与 SPS 评分';
COMMENT ON COLUMN project_scores.project_id IS '关联项目 ID';
COMMENT ON COLUMN project_scores.creator_id IS '关联创作者 ID';
COMMENT ON COLUMN project_scores.predicted_sales IS '预测订单产品数量';
COMMENT ON COLUMN project_scores.sps_score IS '映射后的 SPS 评分 0-100';
COMMENT ON COLUMN project_scores.confidence IS '模型置信度';
COMMENT ON COLUMN project_scores.contact_probability IS '联系概率';
COMMENT ON COLUMN project_scores.predicted_response_rate IS '预测回复率';

CREATE INDEX IF NOT EXISTS idx_project_scores_creator_id ON project_scores (creator_id);
CREATE INDEX IF NOT EXISTS idx_project_scores_predicted_sales ON project_scores (predicted_sales);
