-- Migration 011: Add bd_decisions table for per-user BD audit

CREATE TABLE IF NOT EXISTS bd_decisions (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES creators(id) NOT NULL,
    user_id INTEGER REFERENCES users(id) NOT NULL,
    decision VARCHAR(20) NOT NULL,
    previous_decision VARCHAR(20),
    note TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(creator_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_bd_decisions_creator ON bd_decisions (creator_id);
CREATE INDEX IF NOT EXISTS idx_bd_decisions_user ON bd_decisions (user_id);
CREATE INDEX IF NOT EXISTS idx_bd_decisions_decision ON bd_decisions (decision);
