-- 0003: one EDGAR accession can belong to several CIKs.
--
-- A parent and its operating partnership file a combined 10-K under a single accession number, and the
-- daily index lists one line per co-filer. `accession` alone is therefore not a key: loading both rows
-- violated filings_pkey. The key is (cik, accession); a plain index keeps accession lookups fast.
ALTER TABLE filings DROP CONSTRAINT IF EXISTS filings_pkey;
ALTER TABLE filings ADD CONSTRAINT filings_pkey PRIMARY KEY (cik, accession);
CREATE INDEX IF NOT EXISTS filings_accession_idx ON filings (accession);
