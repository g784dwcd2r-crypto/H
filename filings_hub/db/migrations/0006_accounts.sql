-- 0006: accounts and the preference spine (used when the API serves from Postgres).
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    plan        TEXT NOT NULL DEFAULT 'free',
    locale      TEXT,
    timezone    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope       TEXT NOT NULL,          -- global | sector | company | statement | export
    scope_key   TEXT NOT NULL DEFAULT '',
    key         TEXT NOT NULL,
    value       JSONB,
    source      TEXT NOT NULL DEFAULT 'explicit',   -- explicit | inferred | preset
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, scope, scope_key, key)
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash  TEXT PRIMARY KEY,
    record      JSONB NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS pref_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    key         TEXT,
    scope       TEXT,
    old         JSONB,
    new         JSONB,
    source      TEXT,
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pref_events_user_idx ON pref_events (user_id, at DESC);
