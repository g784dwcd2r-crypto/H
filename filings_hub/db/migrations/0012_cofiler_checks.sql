-- Quality results belong to an issuer even when a filing accession is shared by co-filers.
ALTER TABLE statement_checks DROP CONSTRAINT IF EXISTS statement_checks_pkey;
ALTER TABLE statement_checks ADD CONSTRAINT statement_checks_pkey PRIMARY KEY (cik, accession, statement, check_name);
