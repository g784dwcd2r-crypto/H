-- Immutable code-point spans. Embeddings never grant access to their parent document.
CREATE TABLE IF NOT EXISTS research_text_projections (
    projection_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES research_versions(version_id),
    extractor_version TEXT NOT NULL,
    text_content TEXT NOT NULL,
    pages TEXT NOT NULL,
    prepared_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_prepared_projection (
    version_id TEXT PRIMARY KEY REFERENCES research_versions(version_id),
    projection_id TEXT NOT NULL REFERENCES research_text_projections(projection_id)
);
CREATE TABLE IF NOT EXISTS research_preparation_failures (
    version_id TEXT NOT NULL REFERENCES research_versions(version_id),
    extractor_version TEXT NOT NULL,
    error_code TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    failed_at TEXT NOT NULL,
    PRIMARY KEY(version_id, extractor_version)
);
CREATE TABLE IF NOT EXISTS research_prepared_versions (
    version_id TEXT PRIMARY KEY REFERENCES research_versions(version_id),
    prepared_at TEXT NOT NULL,
    span_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS research_spans (
    span_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES research_versions(version_id),
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    text_content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_spans_version_idx ON research_spans(version_id);
CREATE TABLE IF NOT EXISTS research_span_projections (
    span_id TEXT PRIMARY KEY REFERENCES research_spans(span_id),
    projection_id TEXT NOT NULL REFERENCES research_text_projections(projection_id)
);
CREATE TABLE IF NOT EXISTS research_span_terms (
    span_id TEXT NOT NULL REFERENCES research_spans(span_id),
    term TEXT NOT NULL,
    PRIMARY KEY(term, span_id)
);
CREATE TABLE IF NOT EXISTS research_embeddings (
    span_id TEXT NOT NULL REFERENCES research_spans(span_id),
    model TEXT NOT NULL,
    vector TEXT NOT NULL,
    embedded_at TEXT NOT NULL,
    PRIMARY KEY(span_id, model)
);
-- Same transaction adapter and authorization locks as accounts/projects.
CREATE TABLE IF NOT EXISTS cited_research_runs (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    project_id TEXT,
    record JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS cited_research_runs_owner_idx ON cited_research_runs(owner_id);
CREATE INDEX IF NOT EXISTS cited_research_runs_project_idx ON cited_research_runs(project_id);
