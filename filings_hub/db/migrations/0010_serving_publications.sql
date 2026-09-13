-- Published in the same transaction as all serving-table changes. Failed loads leave no publication.
CREATE TABLE IF NOT EXISTS serving_publications (
    publication_id UUID PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('full', 'incremental')),
    published_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    counts JSONB NOT NULL,
    all_periods BOOLEAN NOT NULL,
    source_root TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS serving_publications_recent ON serving_publications (published_at DESC);
