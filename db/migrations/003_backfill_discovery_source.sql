-- Migration 003: Backfill discovery_strategy / discovered_via for historical creators
-- Run: psql -U miner -d craftifyx_miner -f db/migrations/003_backfill_discovery_source.sql

-- 1. Seeds imported via CSV: mark as csv_import
UPDATE creators
SET discovery_strategy = 'csv_import'
WHERE is_seed = true AND discovery_strategy IS NULL;

-- 2. Non-seeds whose discovered_date matches a discovery batch (same calendar day)
UPDATE creators c
SET discovery_strategy = 'seed_following',
    discovered_via = 'matched_from_batch'
FROM discovery_batches db
WHERE c.is_seed = false
  AND c.discovery_strategy IS NULL
  AND c.discovered_date = db.batch_date;

-- 3. Remaining rows with NULL strategy
UPDATE creators
SET discovery_strategy = 'legacy'
WHERE discovery_strategy IS NULL;
