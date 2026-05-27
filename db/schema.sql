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
    interaction_data JSONB,
    collected_at TIMESTAMP DEFAULT NOW()
);

-- 3. creator_features (8 维指标)
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
    audience_segment_score FLOAT
);

-- 4. creator_graph (关系图谱)
CREATE TABLE IF NOT EXISTS creator_graph (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id),
    connected_creator_id INTEGER REFERENCES creators(id),
    connection_type VARCHAR(20),
    weight FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT NOW()
);

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

-- 11. login_attempts (登录审计)
CREATE TABLE IF NOT EXISTS login_attempts (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50),
    ip_address INET,
    success BOOLEAN NOT NULL,
    user_agent TEXT,
    attempted_at TIMESTAMP DEFAULT NOW()
);
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
CREATE INDEX IF NOT EXISTS idx_bd_decisions_creator ON bd_decisions (creator_id);
CREATE INDEX IF NOT EXISTS idx_bd_decisions_user ON bd_decisions (user_id);
CREATE INDEX IF NOT EXISTS idx_bd_decisions_decision ON bd_decisions (decision);
