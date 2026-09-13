-- Dedicated platform operators. Neither users nor tenant roles imply platform privileges.
CREATE TABLE IF NOT EXISTS platform_admins (id TEXT PRIMARY KEY, record JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS platform_admin_sessions (
    id TEXT PRIMARY KEY, admin_id TEXT NOT NULL REFERENCES platform_admins(id), record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS platform_admin_sessions_admin_idx ON platform_admin_sessions(admin_id);
CREATE TABLE IF NOT EXISTS platform_admin_audit (
    id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, action TEXT NOT NULL, target_id TEXT NOT NULL, record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS platform_admin_audit_action_idx ON platform_admin_audit(action);
CREATE INDEX IF NOT EXISTS platform_admin_audit_target_idx ON platform_admin_audit(target_id);
CREATE TABLE IF NOT EXISTS platform_account_controls (
    id TEXT PRIMARY KEY REFERENCES users(id), record JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_admin_settings (id TEXT PRIMARY KEY, record JSONB NOT NULL);
-- A durable intent precedes any mutation in the separately owned research-job engine.
CREATE TABLE IF NOT EXISTS platform_admin_job_commands (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, status TEXT NOT NULL, record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS platform_admin_job_commands_status_idx ON platform_admin_job_commands(status);
