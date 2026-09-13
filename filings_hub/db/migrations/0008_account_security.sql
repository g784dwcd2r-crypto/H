-- Durable sessions and tenant authorization. The record preserves API timestamps as ISO strings;
-- indexed identity columns and foreign keys constrain ownership independently of JSON contents.
CREATE TABLE IF NOT EXISTS account_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS account_sessions_user_idx ON account_sessions (user_id);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    record JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS organization_memberships (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    record JSONB NOT NULL,
    UNIQUE (organization_id, user_id)
);
CREATE INDEX IF NOT EXISTS organization_memberships_user_idx ON organization_memberships (user_id);

CREATE TABLE IF NOT EXISTS account_security_audit (
    id TEXT PRIMARY KEY,
    organization_id TEXT REFERENCES organizations(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS account_security_audit_org_idx ON account_security_audit (organization_id);
CREATE INDEX IF NOT EXISTS account_security_audit_actor_idx ON account_security_audit (actor_id);
