-- 0002: make company search index-friendly at full EDGAR scale (~900k companies).
--
-- The search query is a UNION of one branch per identifier (name, ticker, CIK) so each branch can use
-- an index; a single OR across the three columns forces a sequential scan instead.
--
-- The name branch needs a trigram index for the leading-wildcard LIKE. pg_trgm is a trusted extension
-- on PostgreSQL 13+ and on the managed providers, but a restricted role may still be refused it, so the
-- whole block is wrapped: if the extension cannot be created the migration still succeeds and company
-- search falls back to a sequential scan.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE INDEX IF NOT EXISTS companies_name_trgm_idx ON companies USING gin (lower(name) gin_trgm_ops);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_trgm unavailable (%); company search falls back to a sequential scan', SQLERRM;
END $$;

-- Ranking columns for the candidate set.
CREATE INDEX IF NOT EXISTS companies_rank_idx ON companies (is_active DESC, filing_count DESC);
