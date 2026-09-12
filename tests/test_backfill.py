"""Backfill acceptance tests: the plan requires re-running a day to be a no-op."""

from __future__ import annotations

import hashlib
from datetime import date

import pytest

from filings_hub.ingest.backfill import run_backfill
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx

TABLES = ("companies", "tickers", "filings", "periods", "facts", "statements", "statement_checks")


def _fingerprint(storage: Storage) -> dict[str, tuple[int, str]]:
    """Row count and an order-independent content hash per table."""
    duck = Duck(storage)
    try:
        duck.create_views()
        out = {}
        for t in TABLES:
            rows = duck.fetch_dicts(f"SELECT * FROM {t}")
            blob = "\n".join(sorted(repr(sorted(r.items(), key=lambda kv: kv[0])) for r in rows))
            out[t] = (len(rows), hashlib.sha256(blob.encode()).hexdigest())
        return out
    finally:
        duck.close()


def test_backfill_is_idempotent(tmp_path):
    storage = Storage(str(tmp_path / "lake"))
    fx.seed_raw(storage, date(2026, 9, 11))

    first = run_backfill(storage, workers=1, skip_download=True, load_db=False, today=date(2026, 9, 11))
    assert first.status == "ok", first.summary()
    before = _fingerprint(storage)

    second = run_backfill(storage, workers=1, skip_download=True, load_db=False, today=date(2026, 9, 11))
    assert second.status == "ok", second.summary()
    after = _fingerprint(storage)

    assert before == after, "a second backfill changed the data"
    assert all(n > 0 for n, _ in before.values())

    duck = Duck(storage)
    try:
        duck.create_views()
        # every run is still recorded, and the rebuild leaves no duplicated statement rows behind
        assert duck.fetch_dicts("SELECT count(*) AS n FROM run_log")[0]["n"] == 2
        dupes = duck.fetch_dicts(
            "SELECT count(*) AS n FROM (SELECT accession, statement, line_order, period_end, qtrs, "
            "is_parenthetical, count(*) c FROM statements GROUP BY ALL HAVING c > 1)"
        )
        assert dupes[0]["n"] == 0
    finally:
        duck.close()


def test_backfill_without_raw_files_fails_cleanly(tmp_path):
    run = run_backfill(Storage(str(tmp_path / "empty")), workers=1, skip_download=True, load_db=False)
    assert run.status == "failed" and "raw bulk files missing" in run.error


@pytest.mark.parametrize("source", ["submissions", "companyfacts", "company_tickers"])
def test_raw_layer_is_reused_not_refetched(tmp_path, source):
    """Rebuilds never need the SEC: the raw bytes are dated and picked up by latest_raw."""
    from filings_hub.ingest.bulk import latest_raw

    storage = Storage(str(tmp_path / "lake"))
    day = fx.seed_raw(storage, date(2026, 9, 11))
    rel = latest_raw(storage, source)
    assert rel is not None and storage.exists(rel) and day.isoformat() in rel
