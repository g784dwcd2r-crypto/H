-- Scoped, revisioned user-authored projects. Evidence pointers do not copy provider content.
CREATE TABLE IF NOT EXISTS research_projects (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id),
    organization_id TEXT REFERENCES organizations(id),
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS research_projects_owner_idx ON research_projects (owner_id);
CREATE INDEX IF NOT EXISTS research_projects_org_idx ON research_projects (organization_id);
CREATE TABLE IF NOT EXISTS research_notes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS research_notes_project_idx ON research_notes (project_id);
