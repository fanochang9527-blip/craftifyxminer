-- 修复 seed_follower_snapshots 缺少 growth_monitor 所需的 anomaly 列
ALTER TABLE seed_follower_snapshots
    ADD COLUMN IF NOT EXISTS anomaly_type VARCHAR(20),
    ADD COLUMN IF NOT EXISTS anomaly_note TEXT;
