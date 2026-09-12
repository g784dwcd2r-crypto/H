-- 0004: per-step timings on run_log, so a slow backfill can be attributed to a step.
ALTER TABLE run_log ADD COLUMN IF NOT EXISTS steps TEXT[];
