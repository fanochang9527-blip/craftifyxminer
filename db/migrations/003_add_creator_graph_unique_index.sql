-- Migration: 为 creator_graph 添加唯一索引，支持 following 关系去重
-- 使得 INSERT ON CONFLICT DO NOTHING 可以正常工作

CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_unique_relation
    ON creator_graph (creator_id, connected_creator_id, connection_type);
