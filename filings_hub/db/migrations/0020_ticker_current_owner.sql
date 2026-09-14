-- 0020: which company currently owns a reused ticker symbol. A symbol gets reused after a company
-- delists; both companies keep a row, and is_current marks the one still filing so a ticker lookup
-- never lands on the dead company. Set by mark_current_owner at universe-build time.
ALTER TABLE tickers ADD COLUMN IF NOT EXISTS is_current BOOLEAN;
CREATE INDEX IF NOT EXISTS tickers_ticker_current_idx ON tickers (ticker) WHERE is_current;
