-- One global campaign, individual accounts only. Never allocate by email submission or region.
CREATE TABLE IF NOT EXISTS launch_memberships (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN ('reserved', 'waitlisted')),
    position INTEGER NOT NULL CHECK (position > 0),
    record JSONB NOT NULL,
    UNIQUE (campaign_id, user_id),
    UNIQUE (campaign_id, position),
    CHECK ((status = 'reserved' AND position <= 20) OR (status = 'waitlisted' AND position > 20))
);
CREATE INDEX IF NOT EXISTS launch_memberships_campaign_idx ON launch_memberships(campaign_id, status);
CREATE TABLE IF NOT EXISTS demo_requests (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    caller_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('new', 'contacted', 'scheduled', 'completed')),
    created_at TEXT NOT NULL,
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS demo_requests_status_idx ON demo_requests(status, created_at);
CREATE INDEX IF NOT EXISTS demo_requests_email_idx ON demo_requests(email, created_at);
CREATE INDEX IF NOT EXISTS demo_requests_caller_idx ON demo_requests(caller_hash, created_at);
