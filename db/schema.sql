-- CraftifyX Miner 6.0 / 7.0 对齐 — 数据库 Schema (9 张核心表)
-- creator_features 9 维指标（已去除 circle_influence_score、data_confidence，新增 audience_segment_score）
-- 执行（库名/用户以 .env 为准，默认）: psql -U miner -d craftifyx_miner -f db/schema.sql

-- 1. creators (主档案)
CREATE TABLE IF NOT EXISTS creators (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    platform VARCHAR(64) NOT NULL DEFAULT 'twitter',
    platform_account_id TEXT NOT NULL,
    sales_transaction_count INTEGER DEFAULT 0,
    followers INTEGER,
    following INTEGER,
    tweets_count INTEGER,
    bio TEXT,
    website TEXT,
    account_age INTEGER,
    is_seed BOOLEAN DEFAULT false,
    creator_type_manual VARCHAR(20),
    creator_type_auto VARCHAR(20),
    total_sales FLOAT DEFAULT 0,
    has_merch_experience BOOLEAN,
    discovered_date DATE DEFAULT CURRENT_DATE,
    discovered_via VARCHAR(50),
    discovery_strategy VARCHAR(20),
    anchor_seed TEXT,
    bd_status VARCHAR(20) DEFAULT 'pending',
    bd_assigned_to VARCHAR(50),
    bd_decision VARCHAR(20),
    bd_decision_note TEXT,
    creator_segment VARCHAR(20),
    last_bd_update TIMESTAMP,
    last_scraped_as_anchor TIMESTAMP,
    first_seen_at TIMESTAMP DEFAULT NOW()
);
COMMENT ON TABLE creators IS '创作者主档案表：存储从社交平台抓取的核心创作者资料、BD 审核状态及发现来源';
COMMENT ON COLUMN creators.id IS '自增主键';
COMMENT ON COLUMN creators.username IS '创作者在社交平台的用户名';
COMMENT ON COLUMN creators.platform IS '社交平台标识，默认 twitter';
COMMENT ON COLUMN creators.platform_account_id IS '平台侧唯一账号 ID（如 Twitter 的 user_id）';
COMMENT ON COLUMN creators.sales_transaction_count IS '历史成交笔数（来自销售反馈回写）';
COMMENT ON COLUMN creators.followers IS '粉丝数（最近一次抓取）';
COMMENT ON COLUMN creators.following IS '关注数（最近一次抓取）';
COMMENT ON COLUMN creators.tweets_count IS '推文/发帖总数（最近一次抓取）';
COMMENT ON COLUMN creators.bio IS '个人简介文本';
COMMENT ON COLUMN creators.website IS '个人主页或店铺链接（用于判断变现经验）';
COMMENT ON COLUMN creators.account_age IS '账号年龄（天）';
COMMENT ON COLUMN creators.is_seed IS '是否为种子创作者：已有合作历史或手动导入的重点创作者';
COMMENT ON COLUMN creators.creator_type_manual IS '人工标注的创作者类型（oc_creator / vtuber / fan_artist / game_creator / content_creator）';
COMMENT ON COLUMN creators.creator_type_auto IS 'AI 自动识别的创作者类型（pipeline/ai_filter 输出）';
COMMENT ON COLUMN creators.total_sales IS '历史总销售额（来自销售反馈回写）';
COMMENT ON COLUMN creators.has_merch_experience IS '是否有周边/商品销售经验（通过 bio/website 规则判断）';
COMMENT ON COLUMN creators.discovered_date IS '首次发现日期';
COMMENT ON COLUMN creators.discovered_via IS '发现渠道（如 hashtag_explore / geo_explore / seed_following）';
COMMENT ON COLUMN creators.discovery_strategy IS '发现策略（如 seed_following / time_explore / csv_import / legacy）';
COMMENT ON COLUMN creators.anchor_seed IS '关联的种子创作者用户名（用于追踪发现链路）';
COMMENT ON COLUMN creators.bd_status IS 'BD 跟进状态：pending / rule_passed / rule_rejected / ai_passed / ai_rejected';
COMMENT ON COLUMN creators.bd_assigned_to IS '分配的 BD 负责人用户名';
COMMENT ON COLUMN creators.bd_decision IS 'BD 最终决策：interested / rejected_unfit / rejected_not_creator';
COMMENT ON COLUMN creators.bd_decision_note IS 'BD 决策备注';
COMMENT ON COLUMN creators.creator_segment IS '受众分段：multi_platform / mainstream / nsfw';
COMMENT ON COLUMN creators.last_bd_update IS '最后一次 BD 状态更新时间';
COMMENT ON COLUMN creators.last_scraped_as_anchor IS '最后一次作为种子创作者被抓取的时间';
COMMENT ON COLUMN creators.first_seen_at IS '系统首次记录时间';

-- 2. tweets (推文数据)
CREATE TABLE IF NOT EXISTS tweets (
    id SERIAL PRIMARY KEY,
    tweet_id TEXT UNIQUE,
    creator_id INTEGER REFERENCES creators(id),
    likes INTEGER,
    retweets INTEGER,
    replies INTEGER,
    views INTEGER,
    created_at TIMESTAMP,
    text TEXT,
    media_urls TEXT[],
    media_types TEXT[],
    interaction_data JSONB,
    collected_at TIMESTAMP DEFAULT NOW()
);
COMMENT ON TABLE tweets IS '推文/帖子数据表：存储创作者的历史推文，用于计算互动率、传播力等特征';
COMMENT ON COLUMN tweets.id IS '自增主键';
COMMENT ON COLUMN tweets.tweet_id IS '平台侧推文唯一 ID';
COMMENT ON COLUMN tweets.creator_id IS '关联创作者 ID（外键）';
COMMENT ON COLUMN tweets.likes IS '点赞数';
COMMENT ON COLUMN tweets.retweets IS '转发/转推数';
COMMENT ON COLUMN tweets.replies IS '回复数';
COMMENT ON COLUMN tweets.views IS '浏览/展示数';
COMMENT ON COLUMN tweets.created_at IS '推文发布时间';
COMMENT ON COLUMN tweets.text IS '推文文本内容';
COMMENT ON COLUMN tweets.media_urls IS '附件媒体 URL 列表（图片、视频等）';
COMMENT ON COLUMN tweets.media_types IS '附件媒体类型列表';
COMMENT ON COLUMN tweets.interaction_data IS '原始互动数据 JSON（保留扩展字段）';
COMMENT ON COLUMN tweets.collected_at IS '数据采集时间';

-- 3. creator_features (9 维组合特征 + 5 维原始特征)
CREATE TABLE IF NOT EXISTS creator_features (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) UNIQUE,
    calculated_at TIMESTAMP DEFAULT NOW(),
    audience_score FLOAT,
    engagement_score FLOAT,
    virality_score FLOAT,
    growth_score FLOAT,
    posting_score FLOAT,
    monetization_score FLOAT,
    character_consistency FLOAT,
    community_score FLOAT,
    audience_segment_score FLOAT,
    -- 原始特征（用于 ML V2 实验组）
    social_engagement_rate FLOAT,
    conversation_rate FLOAT,
    fanart_ratio FLOAT,
    virality_raw_ratio FLOAT,
    monthly_engagement_base FLOAT
);
COMMENT ON TABLE creator_features IS '创作者特征表：存储 9 维组合评分 + 5 维原始特征，由 pipeline/feature_engine 计算';
COMMENT ON COLUMN creator_features.id IS '自增主键';
COMMENT ON COLUMN creator_features.creator_id IS '关联创作者 ID（外键，唯一）';
COMMENT ON COLUMN creator_features.calculated_at IS '特征计算时间';
COMMENT ON COLUMN creator_features.audience_score IS '受众评分：基于粉丝数及对假粉比例的惩罚（来源：feature_engine.calc_audience）';
COMMENT ON COLUMN creator_features.engagement_score IS '互动评分：基于点赞/转发/回复的时序加权平均互动率（来源：feature_engine.calc_engagement）';
COMMENT ON COLUMN creator_features.virality_score IS '传播力评分：top3 爆款帖与月均互动比值，封顶 100（来源：feature_engine.calc_virality）';
COMMENT ON COLUMN creator_features.growth_score IS '增长评分：基于粉丝历史快照的月环比/月净增长（来源：feature_engine.calc_growth / growth_monitor）';
COMMENT ON COLUMN creator_features.posting_score IS '发帖活跃度评分：基于近 30 天实际发帖数估算（来源：feature_engine.calc_posting）';
COMMENT ON COLUMN creator_features.monetization_score IS '变现潜力评分：基于 bio/website 中的电商关键词规则匹配（来源：feature_engine.calc_monetization / bio_rule_filter）';
COMMENT ON COLUMN creator_features.character_consistency IS '角色一致性评分：基于图片 media_url 的域名集中度（来源：feature_engine.calc_character_consistency）';
COMMENT ON COLUMN creator_features.community_score IS '社区影响力评分：基于 fanart 转推权重及 mention 互动（来源：feature_engine.calc_community）';
COMMENT ON COLUMN creator_features.audience_segment_score IS '受众分段评分：multi_platform(80) / mainstream(50) / nsfw(20)（来源：feature_engine.calc_audience_segment）';
COMMENT ON COLUMN creator_features.social_engagement_rate IS '社交互动率：(avg_likes + avg_retweets) / followers * 100（来源：feature_engine.calc_social_engagement_rate）';
COMMENT ON COLUMN creator_features.conversation_rate IS '对话率：avg_replies / followers * 100（来源：feature_engine.calc_conversation_rate）';
COMMENT ON COLUMN creator_features.fanart_ratio IS '同人作品占比：含 fanart 关键词的推文占比（来源：feature_engine.calc_fanart_ratio）';
COMMENT ON COLUMN creator_features.virality_raw_ratio IS '原始传播比率：top3_avg / monthly_avg，不封顶（来源：feature_engine.calc_virality_raw）';
COMMENT ON COLUMN creator_features.monthly_engagement_base IS '月度互动基数：保留 monthly_avg 绝对值（来源：feature_engine.calc_monthly_engagement_base）';

-- 4. creator_graph (关系图谱)
CREATE TABLE IF NOT EXISTS creator_graph (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id),
    connected_creator_id INTEGER REFERENCES creators(id),
    connection_type VARCHAR(20),
    weight FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT NOW()
);
COMMENT ON TABLE creator_graph IS '创作者关系图谱：记录种子创作者与其关注/互动对象之间的关联';
COMMENT ON COLUMN creator_graph.id IS '自增主键';
COMMENT ON COLUMN creator_graph.creator_id IS '源创作者 ID（外键）';
COMMENT ON COLUMN creator_graph.connected_creator_id IS '关联创作者 ID（外键）';
COMMENT ON COLUMN creator_graph.connection_type IS '关系类型：follow / mention / retweet / seed 等';
COMMENT ON COLUMN creator_graph.weight IS '关系权重，默认 1.0';
COMMENT ON COLUMN creator_graph.created_at IS '关系建立时间';

CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_unique_relation
    ON creator_graph (creator_id, connected_creator_id, connection_type);

-- 5. creator_scores (SPS 评分 + 中心度)
CREATE TABLE IF NOT EXISTS creator_scores (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) UNIQUE,
    creator_type VARCHAR(20),
    sellability_score FLOAT,
    is_sellable BOOLEAN,
    predicted_sales FLOAT,
    sps_score FLOAT,
    confidence FLOAT,
    centrality_tier VARCHAR(20),
    seed_connections INTEGER,
    contact_probability FLOAT,
    predicted_response_rate FLOAT,
    updated_at TIMESTAMP DEFAULT NOW()
);
COMMENT ON TABLE creator_scores IS '创作者评分表：存储 sellability/sps 双模型输出、中心度分层及联系概率';
COMMENT ON COLUMN creator_scores.id IS '自增主键';
COMMENT ON COLUMN creator_scores.creator_id IS '关联创作者 ID（外键，唯一）';
COMMENT ON COLUMN creator_scores.creator_type IS '创作者类型（合并人工标注与自动识别）';
COMMENT ON COLUMN creator_scores.sellability_score IS '可卖货评分 0-100（Model A：LogisticRegression/XGBoost，来源：pipeline/sellability_model）';
COMMENT ON COLUMN creator_scores.is_sellable IS '是否达到可卖货阈值（SELLABILITY_SCORE_THRESHOLD）';
COMMENT ON COLUMN creator_scores.predicted_sales IS '预测销量（来源：pipeline/sps_model.predict_sales 或 weighted-sum fallback）';
COMMENT ON COLUMN creator_scores.sps_score IS 'SPS 评分 0-100（Model B：Ridge/XGBoost，来源：pipeline/sps_model / sps_scorer）';
COMMENT ON COLUMN creator_scores.confidence IS '模型置信度（预留）';
COMMENT ON COLUMN creator_scores.centrality_tier IS '中心度层级：Hub(>=5) / Connector(2-4) / Peripheral(0-1)';
COMMENT ON COLUMN creator_scores.seed_connections IS '与该创作者关联的种子创作者数量';
COMMENT ON COLUMN creator_scores.contact_probability IS '联系概率：SPS*0.8 + Monetization*0.2 归一化到 0-1';
COMMENT ON COLUMN creator_scores.predicted_response_rate IS '预测回复率（当前与 contact_probability 同值）';
COMMENT ON COLUMN creator_scores.updated_at IS '评分更新时间';

-- 6. sales_feedback (系统进化核心)
CREATE TABLE IF NOT EXISTS sales_feedback (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id),
    sku_id TEXT,
    gmv FLOAT,
    units_sold INTEGER,
    launch_date DATE,
    conversion_rate FLOAT,
    bd_contact_id INTEGER,
    days_to_close INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
COMMENT ON TABLE sales_feedback IS '销售反馈表：记录创作者带货的实际销售数据，用于模型进化与效果追踪';
COMMENT ON COLUMN sales_feedback.id IS '自增主键';
COMMENT ON COLUMN sales_feedback.creator_id IS '关联创作者 ID（外键）';
COMMENT ON COLUMN sales_feedback.sku_id IS '商品 SKU 编号';
COMMENT ON COLUMN sales_feedback.gmv IS '成交金额（GMV）';
COMMENT ON COLUMN sales_feedback.units_sold IS '销售数量';
COMMENT ON COLUMN sales_feedback.launch_date IS '商品上架/推广日期';
COMMENT ON COLUMN sales_feedback.conversion_rate IS '转化率';
COMMENT ON COLUMN sales_feedback.bd_contact_id IS '负责该笔销售的 BD 人员 ID';
COMMENT ON COLUMN sales_feedback.days_to_close IS '从首次联系到成交的天数';
COMMENT ON COLUMN sales_feedback.created_at IS '记录创建时间';

-- 7. outreach_log (BD 联系追踪)
CREATE TABLE IF NOT EXISTS outreach_log (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id),
    bd_username VARCHAR(50),
    contact_channel VARCHAR(20),
    contacted_at TIMESTAMP,
    response_received BOOLEAN,
    response_time_hours INTEGER,
    deal_status VARCHAR(20),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
COMMENT ON TABLE outreach_log IS 'BD 外联日志：记录每次与创作者的沟通尝试及反馈';
COMMENT ON COLUMN outreach_log.id IS '自增主键';
COMMENT ON COLUMN outreach_log.creator_id IS '关联创作者 ID（外键）';
COMMENT ON COLUMN outreach_log.bd_username IS '执行外联的 BD 用户名';
COMMENT ON COLUMN outreach_log.contact_channel IS '联系渠道：email / dm / twitter / other';
COMMENT ON COLUMN outreach_log.contacted_at IS '联系时间';
COMMENT ON COLUMN outreach_log.response_received IS '是否收到回复';
COMMENT ON COLUMN outreach_log.response_time_hours IS '回复耗时（小时）';
COMMENT ON COLUMN outreach_log.deal_status IS '交易状态：negotiating / signed / declined / no_response';
COMMENT ON COLUMN outreach_log.notes IS '沟通备注';
COMMENT ON COLUMN outreach_log.created_at IS '记录创建时间';

-- 8. cost_tracking (成本监控)
CREATE TABLE IF NOT EXISTS cost_tracking (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    apify_cu_used FLOAT DEFAULT 0,
    apify_cost_usd FLOAT DEFAULT 0,
    llm_tokens_used INTEGER DEFAULT 0,
    llm_cost_usd FLOAT DEFAULT 0,
    proxy_datacenter_gb FLOAT DEFAULT 0,
    proxy_residential_gb FLOAT DEFAULT 0,
    proxy_cost_usd FLOAT DEFAULT 0,
    total_cost_usd FLOAT DEFAULT 0,
    UNIQUE(date)
);
COMMENT ON TABLE cost_tracking IS '成本监控表：按日汇总 Apify、LLM、代理等基础设施成本';
COMMENT ON COLUMN cost_tracking.id IS '自增主键';
COMMENT ON COLUMN cost_tracking.date IS '统计日期（唯一）';
COMMENT ON COLUMN cost_tracking.apify_cu_used IS 'Apify 计算单元（CU）使用量';
COMMENT ON COLUMN cost_tracking.apify_cost_usd IS 'Apify 成本（USD）';
COMMENT ON COLUMN cost_tracking.llm_tokens_used IS 'LLM Token 消耗量';
COMMENT ON COLUMN cost_tracking.llm_cost_usd IS 'LLM API 成本（USD）';
COMMENT ON COLUMN cost_tracking.proxy_datacenter_gb IS '数据中心代理流量（GB）';
COMMENT ON COLUMN cost_tracking.proxy_residential_gb IS '住宅代理流量（GB）';
COMMENT ON COLUMN cost_tracking.proxy_cost_usd IS '代理成本（USD）';
COMMENT ON COLUMN cost_tracking.total_cost_usd IS '当日总成本（USD）';

-- 9. discovery_batches (发现批次追踪)
CREATE TABLE IF NOT EXISTS discovery_batches (
    id SERIAL PRIMARY KEY,
    batch_date DATE NOT NULL DEFAULT CURRENT_DATE,
    batch_type VARCHAR(20),
    anchor_seeds TEXT[],
    exploration_ratio FLOAT,
    raw_discovered INTEGER DEFAULT 0,
    after_ai_filter INTEGER DEFAULT 0,
    after_deep_scrape INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
COMMENT ON TABLE discovery_batches IS '发现批次追踪表：记录每次创作者发现任务的配置与结果漏斗';
COMMENT ON COLUMN discovery_batches.id IS '自增主键';
COMMENT ON COLUMN discovery_batches.batch_date IS '批次日期';
COMMENT ON COLUMN discovery_batches.batch_type IS '批次类型：daily / manual / backfill';
COMMENT ON COLUMN discovery_batches.anchor_seeds IS '该批次使用的种子创作者列表';
COMMENT ON COLUMN discovery_batches.exploration_ratio IS '探索比例（非种子占比）';
COMMENT ON COLUMN discovery_batches.raw_discovered IS '原始发现数量';
COMMENT ON COLUMN discovery_batches.after_ai_filter IS 'AI 过滤后剩余数量';
COMMENT ON COLUMN discovery_batches.after_deep_scrape IS '深度抓取后剩余数量';
COMMENT ON COLUMN discovery_batches.created_at IS '批次创建时间';

-- 10. users (登录与权限)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name VARCHAR(100),
    role VARCHAR(20) NOT NULL DEFAULT 'bd',
    is_active BOOLEAN DEFAULT true,
    locked_until TIMESTAMP,
    failed_attempts INTEGER DEFAULT 0,
    last_login_at TIMESTAMP,
    password_changed_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);
COMMENT ON TABLE users IS '系统用户表：存储 BD 及相关人员的登录凭证与权限';
COMMENT ON COLUMN users.id IS '自增主键';
COMMENT ON COLUMN users.username IS '登录用户名（唯一）';
COMMENT ON COLUMN users.password_hash IS '密码哈希（bcrypt）';
COMMENT ON COLUMN users.display_name IS '显示名称';
COMMENT ON COLUMN users.role IS '角色：admin / bd / viewer';
COMMENT ON COLUMN users.is_active IS '账号是否激活';
COMMENT ON COLUMN users.locked_until IS '账号锁定截止时间（登录失败过多时触发）';
COMMENT ON COLUMN users.failed_attempts IS '连续登录失败次数';
COMMENT ON COLUMN users.last_login_at IS '最后登录时间';
COMMENT ON COLUMN users.password_changed_at IS '密码最后修改时间';
COMMENT ON COLUMN users.created_at IS '账号创建时间';

-- 11. login_attempts (登录审计)
CREATE TABLE IF NOT EXISTS login_attempts (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50),
    ip_address INET,
    success BOOLEAN NOT NULL,
    user_agent TEXT,
    attempted_at TIMESTAMP DEFAULT NOW()
);
COMMENT ON TABLE login_attempts IS '登录审计表：记录每次登录尝试，用于安全审计与风控';
COMMENT ON COLUMN login_attempts.id IS '自增主键';
COMMENT ON COLUMN login_attempts.username IS '尝试登录的用户名';
COMMENT ON COLUMN login_attempts.ip_address IS '来源 IP 地址';
COMMENT ON COLUMN login_attempts.success IS '是否登录成功';
COMMENT ON COLUMN login_attempts.user_agent IS '浏览器/客户端 User-Agent';
COMMENT ON COLUMN login_attempts.attempted_at IS '尝试时间';
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts (ip_address, attempted_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_user ON login_attempts (username, attempted_at);

-- 12. model_evaluations (双模型独立评估 — sellability + sps 各一行)
CREATE TABLE IF NOT EXISTS model_evaluations (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(20),        -- 'sellability' | 'sps'
    evaluated_at TIMESTAMP DEFAULT NOW(),
    model_version TEXT,
    n_seeds INTEGER,
    n_predictions INTEGER,
    n_bd_reviewed INTEGER,
    n_interested INTEGER,
    n_rejected INTEGER,
    recall FLOAT,
    precision_score FLOAT,
    f2_score FLOAT,
    precision_at_250 FLOAT,
    spearman_corr FLOAT,
    r2 FLOAT,
    mae FLOAT,
    notes TEXT
);
COMMENT ON TABLE model_evaluations IS '模型评估表：存储 sellability 与 sps 模型的离线评估指标';
COMMENT ON COLUMN model_evaluations.id IS '自增主键';
COMMENT ON COLUMN model_evaluations.model_name IS '模型名称：sellability / sps';
COMMENT ON COLUMN model_evaluations.evaluated_at IS '评估时间';
COMMENT ON COLUMN model_evaluations.model_version IS '模型版本标识';
COMMENT ON COLUMN model_evaluations.n_seeds IS '评估使用的种子数';
COMMENT ON COLUMN model_evaluations.n_predictions IS '预测样本数';
COMMENT ON COLUMN model_evaluations.n_bd_reviewed IS 'BD 已审核样本数';
COMMENT ON COLUMN model_evaluations.n_interested IS 'BD 感兴趣样本数';
COMMENT ON COLUMN model_evaluations.n_rejected IS 'BD 拒绝样本数';
COMMENT ON COLUMN model_evaluations.recall IS '召回率';
COMMENT ON COLUMN model_evaluations.precision_score IS '精确率';
COMMENT ON COLUMN model_evaluations.f2_score IS 'F2 分数（更重视召回）';
COMMENT ON COLUMN model_evaluations.precision_at_250 IS 'Top250 精确率';
COMMENT ON COLUMN model_evaluations.spearman_corr IS 'Spearman 秩相关系数';
COMMENT ON COLUMN model_evaluations.r2 IS 'R² 决定系数';
COMMENT ON COLUMN model_evaluations.mae IS '平均绝对误差';
COMMENT ON COLUMN model_evaluations.notes IS '评估备注';

-- 13. bd_decisions (BD 用户审核决策 — 多用户模式下记录每位用户对创作者的决策)
CREATE TABLE IF NOT EXISTS bd_decisions (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) NOT NULL,
    user_id INTEGER REFERENCES users(id) NOT NULL,
    decision VARCHAR(20) NOT NULL,        -- 'interested' | 'rejected_unfit' | 'rejected_not_creator'
    previous_decision VARCHAR(20),
    note TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(creator_id, user_id)
);
COMMENT ON TABLE bd_decisions IS 'BD 审核决策表：多用户模式下记录每位 BD 对创作者的独立决策';
COMMENT ON COLUMN bd_decisions.id IS '自增主键';
COMMENT ON COLUMN bd_decisions.creator_id IS '创作者 ID（外键）';
COMMENT ON COLUMN bd_decisions.user_id IS 'BD 用户 ID（外键）';
COMMENT ON COLUMN bd_decisions.decision IS '当前决策：interested / rejected_unfit / rejected_not_creator';
COMMENT ON COLUMN bd_decisions.previous_decision IS '修改前的历史决策';
COMMENT ON COLUMN bd_decisions.note IS '决策备注';
COMMENT ON COLUMN bd_decisions.created_at IS '决策创建时间';
COMMENT ON COLUMN bd_decisions.updated_at IS '决策更新时间';
CREATE INDEX IF NOT EXISTS idx_bd_decisions_creator ON bd_decisions (creator_id);
CREATE INDEX IF NOT EXISTS idx_bd_decisions_user ON bd_decisions (user_id);
CREATE INDEX IF NOT EXISTS idx_bd_decisions_decision ON bd_decisions (decision);

-- 14. Growth Score — 粉丝历史快照
ALTER TABLE creators ADD COLUMN IF NOT EXISTS last_follower_refresh_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_creators_last_refresh ON creators (last_follower_refresh_at);

-- 15. 粉丝量急剧下降预警（独立表，不扩展 creators）
CREATE TABLE IF NOT EXISTS follower_alerts (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) ON DELETE CASCADE,
    alerted_at TIMESTAMP DEFAULT NOW(),
    alert_note TEXT,
    UNIQUE(creator_id)
);
COMMENT ON TABLE follower_alerts IS '粉丝量下降预警表：当创作者粉丝数急剧下降时触发预警，跳过评分';
COMMENT ON COLUMN follower_alerts.id IS '自增主键';
COMMENT ON COLUMN follower_alerts.creator_id IS '创作者 ID（外键）';
COMMENT ON COLUMN follower_alerts.alerted_at IS '预警触发时间';
COMMENT ON COLUMN follower_alerts.alert_note IS '预警说明';
CREATE INDEX IF NOT EXISTS idx_follower_alerts_creator ON follower_alerts (creator_id);
CREATE INDEX IF NOT EXISTS idx_follower_alerts_alerted_at ON follower_alerts (alerted_at);

-- 16. 种子粉丝量大幅增长提醒（发现高潜力种子，用于二次合作）
CREATE TABLE IF NOT EXISTS seed_growth_alerts (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) ON DELETE CASCADE,
    alerted_at TIMESTAMP DEFAULT NOW(),
    alert_note TEXT,
    previous_followers INTEGER,
    current_followers INTEGER,
    growth_rate FLOAT,
    UNIQUE(creator_id)
);
COMMENT ON TABLE seed_growth_alerts IS '种子增长提醒表：当种子创作者粉丝量大幅增长时触发，用于二次合作机会挖掘';
COMMENT ON COLUMN seed_growth_alerts.id IS '自增主键';
COMMENT ON COLUMN seed_growth_alerts.creator_id IS '创作者 ID（外键）';
COMMENT ON COLUMN seed_growth_alerts.alerted_at IS '提醒触发时间';
COMMENT ON COLUMN seed_growth_alerts.alert_note IS '提醒说明';
COMMENT ON COLUMN seed_growth_alerts.previous_followers IS '增长前粉丝数';
COMMENT ON COLUMN seed_growth_alerts.current_followers IS '当前粉丝数';
COMMENT ON COLUMN seed_growth_alerts.growth_rate IS '增长率';
CREATE INDEX IF NOT EXISTS idx_seed_growth_alerts_creator ON seed_growth_alerts (creator_id);
CREATE INDEX IF NOT EXISTS idx_seed_growth_alerts_alerted_at ON seed_growth_alerts (alerted_at);

-- 普通创作者粉丝历史快照
CREATE TABLE IF NOT EXISTS creator_snapshots (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) ON DELETE CASCADE,
    observed_at TIMESTAMP DEFAULT NOW(),
    followers INTEGER,
    following INTEGER,
    tweets_count INTEGER,
    source VARCHAR(20),
    anomaly_type VARCHAR(20),
    anomaly_note TEXT,
    UNIQUE(creator_id, observed_at)
);
COMMENT ON TABLE creator_snapshots IS '创作者粉丝历史快照表：定期记录普通创作者的粉丝数据，用于增长监测与异常检测';
COMMENT ON COLUMN creator_snapshots.id IS '自增主键';
COMMENT ON COLUMN creator_snapshots.creator_id IS '创作者 ID（外键）';
COMMENT ON COLUMN creator_snapshots.observed_at IS '观察时间';
COMMENT ON COLUMN creator_snapshots.followers IS '粉丝数';
COMMENT ON COLUMN creator_snapshots.following IS '关注数';
COMMENT ON COLUMN creator_snapshots.tweets_count IS '推文数';
COMMENT ON COLUMN creator_snapshots.source IS '数据来源：api / scrape / backfill';
COMMENT ON COLUMN creator_snapshots.anomaly_type IS '异常类型：drop / spike / stable';
COMMENT ON COLUMN creator_snapshots.anomaly_note IS '异常说明';
CREATE INDEX IF NOT EXISTS idx_snapshots_creator_time ON creator_snapshots (creator_id, observed_at DESC);

-- 种子用户专属粉丝历史快照
CREATE TABLE IF NOT EXISTS seed_follower_snapshots (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) ON DELETE CASCADE,
    observed_at TIMESTAMP DEFAULT NOW(),
    followers INTEGER,
    following INTEGER,
    tweets_count INTEGER,
    source VARCHAR(20),
    batch_tag TEXT,
    UNIQUE(creator_id, observed_at)
);
COMMENT ON TABLE seed_follower_snapshots IS '种子粉丝历史快照表：种子创作者的专属粉丝追踪，粒度更细，用于增长评分计算';
COMMENT ON COLUMN seed_follower_snapshots.id IS '自增主键';
COMMENT ON COLUMN seed_follower_snapshots.creator_id IS '创作者 ID（外键）';
COMMENT ON COLUMN seed_follower_snapshots.observed_at IS '观察时间';
COMMENT ON COLUMN seed_follower_snapshots.followers IS '粉丝数';
COMMENT ON COLUMN seed_follower_snapshots.following IS '关注数';
COMMENT ON COLUMN seed_follower_snapshots.tweets_count IS '推文数';
COMMENT ON COLUMN seed_follower_snapshots.source IS '数据来源';
COMMENT ON COLUMN seed_follower_snapshots.batch_tag IS '批次标签，用于区分不同采集批次';
CREATE INDEX IF NOT EXISTS idx_seed_snapshots_creator_time ON seed_follower_snapshots (creator_id, observed_at DESC);

-- 17. processed_datasets (Apify dataset 去重表，防止 webhook + sync 重复处理)
CREATE TABLE IF NOT EXISTS processed_datasets (
    dataset_id TEXT PRIMARY KEY,
    processed_at TIMESTAMP DEFAULT NOW()
);
COMMENT ON TABLE processed_datasets IS '已处理的 Apify dataset 去重表：webhook 异步回调与同步调用可能处理同一 dataset，通过此表去重';
COMMENT ON COLUMN processed_datasets.dataset_id IS 'Apify dataset ID';
COMMENT ON COLUMN processed_datasets.processed_at IS '处理完成时间';

-- 18. creator_content_analysis (多模态内容风格分析)
CREATE TABLE IF NOT EXISTS creator_content_analysis (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id),
    is_realistic BOOLEAN,
    has_fixed_ip BOOLEAN,
    confidence FLOAT,
    model_used VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',
    analyzed_at TIMESTAMP DEFAULT NOW(),
    raw_result JSONB,
    media_sample TEXT[],
    UNIQUE(creator_id, model_used)
);
COMMENT ON TABLE creator_content_analysis IS '创作者内容风格分析表：存储多模态 LLM 对创作者视觉风格的分析结果';
COMMENT ON COLUMN creator_content_analysis.id IS '自增主键';
COMMENT ON COLUMN creator_content_analysis.creator_id IS '创作者 ID（外键）';
COMMENT ON COLUMN creator_content_analysis.is_realistic IS '是否为写实风格';
COMMENT ON COLUMN creator_content_analysis.has_fixed_ip IS '是否有固定 IP/角色形象';
COMMENT ON COLUMN creator_content_analysis.confidence IS '模型置信度';
COMMENT ON COLUMN creator_content_analysis.model_used IS '使用的分析模型（如 GPT-4o / Claude）';
COMMENT ON COLUMN creator_content_analysis.status IS '分析状态：pending / processing / completed / failed';
COMMENT ON COLUMN creator_content_analysis.analyzed_at IS '分析完成时间';
COMMENT ON COLUMN creator_content_analysis.raw_result IS '原始分析结果 JSON';
COMMENT ON COLUMN creator_content_analysis.media_sample IS '用于分析的媒体样本 URL 列表';
CREATE INDEX IF NOT EXISTS idx_content_analysis_status ON creator_content_analysis (status);
CREATE INDEX IF NOT EXISTS idx_content_analysis_model ON creator_content_analysis (model_used);
