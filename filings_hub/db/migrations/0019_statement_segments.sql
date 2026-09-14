-- 0019: the dimensional context of a statement line. A line's identity is its concept PLUS this:
-- the same tag broken out by product or share class is several lines, not one. Empty for a total.
ALTER TABLE statements ADD COLUMN IF NOT EXISTS segments TEXT;
CREATE INDEX IF NOT EXISTS statements_segments_idx ON statements (cik, statement) WHERE segments IS NOT NULL;
