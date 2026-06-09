-- 新增 processed_datasets 表，防止 webhook 与同步路径重复处理同一 Apify dataset

CREATE TABLE IF NOT EXISTS processed_datasets (
    dataset_id TEXT PRIMARY KEY,
    processed_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE processed_datasets IS '已处理的 Apify dataset 去重表：webhook 异步回调与同步调用可能处理同一 dataset，通过此表去重';
COMMENT ON COLUMN processed_datasets.dataset_id IS 'Apify dataset ID';
COMMENT ON COLUMN processed_datasets.processed_at IS '处理完成时间';
