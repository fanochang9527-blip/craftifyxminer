-- CraftifyX Miner 6.0 / 7.0 对齐 — 数据库 Schema (9 张核心表)
-- creator_features 第 7 维：圈层影响力 circle_influence_score（Miner 7.0），已替代旧版 fan_creator_ratio（粉丝抽样占比）。
-- 执行（库名/用户以 .env 为准，默认）: psql -U miner -d craftifyx_miner -f db/schema.sql

-- 1. creators (主档案)
CREATE TABLE IF NOT EXISTS creators (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    followers INTEGER,
    following INTEGER,
    tweets_count INTEGER,
    bio TEXT,
    website TEXT,
    account_age INTEGER,
    is_seed BOOLEAN DEFAULT false,
    seed_tier VARCHAR(5),
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
    last_bd_update TIMESTAMP,
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

-- 3. creator_features (10 维指标)
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
    -- 圈层影响力 (Miner 7.0): 由「被多少 Seed 关注」归一化到 0–100，见 feature_engine / sps_scorer
    circle_influence_score FLOAT,
    character_consistency FLOAT,
    community_score FLOAT,
    data_confidence FLOAT
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

-- 5. creator_scores (SPS 评分 + 中心度)
CREATE TABLE IF NOT EXISTS creator_scores (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) UNIQUE,
    creator_type VARCHAR(20),
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
