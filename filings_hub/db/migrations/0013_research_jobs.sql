CREATE TABLE IF NOT EXISTS research_jobs (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    not_before DOUBLE PRECISION NOT NULL,
    lease_expires DOUBLE PRECISION,
    record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_jobs_queue_idx ON research_jobs(status,not_before);
-- All corpus-writing jobs share one fence. Scope partitioning is intentionally not claimed.
CREATE TABLE IF NOT EXISTS research_worker_fence (
    id INTEGER PRIMARY KEY,
    job_id TEXT,
    token TEXT,
    expires DOUBLE PRECISION
);
INSERT INTO research_worker_fence(id) VALUES(1) ON CONFLICT DO NOTHING;
