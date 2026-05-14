-- 查询优化索引

CREATE UNIQUE INDEX IF NOT EXISTS uq_creators_platform_account_id
  ON creators(platform, platform_account_id);

CREATE INDEX IF NOT EXISTS idx_creators_username ON creators(username);
CREATE INDEX IF NOT EXISTS idx_creators_seed ON creators(is_seed) WHERE is_seed = true;
CREATE INDEX IF NOT EXISTS idx_creators_bd_status ON creators(bd_status);
CREATE INDEX IF NOT EXISTS idx_creators_discovery_strategy ON creators(discovery_strategy);

CREATE INDEX IF NOT EXISTS idx_tweets_creator ON tweets(creator_id);
CREATE INDEX IF NOT EXISTS idx_tweets_created ON tweets(created_at);

CREATE INDEX IF NOT EXISTS idx_graph_connected ON creator_graph(connected_creator_id, creator_id);
CREATE INDEX IF NOT EXISTS idx_graph_creator ON creator_graph(creator_id);

CREATE INDEX IF NOT EXISTS idx_scores_sps ON creator_scores(sps_score DESC);
CREATE INDEX IF NOT EXISTS idx_scores_sellability ON creator_scores(sellability_score DESC);
CREATE INDEX IF NOT EXISTS idx_scores_is_sellable ON creator_scores(is_sellable);
CREATE INDEX IF NOT EXISTS idx_scores_centrality ON creator_scores(centrality_tier);

CREATE INDEX IF NOT EXISTS idx_cost_date ON cost_tracking(date);
CREATE INDEX IF NOT EXISTS idx_batches_date ON discovery_batches(batch_date);
CREATE INDEX IF NOT EXISTS idx_creators_last_scraped_anchor ON creators(last_scraped_as_anchor);
