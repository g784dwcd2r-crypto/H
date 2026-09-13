from datetime import date

import httpx
import pytest

from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake.storage import Storage
from filings_hub.ownership.ingest import fetch_documents, filing_metadata, parse_index, process_filing, sync_ownership
from filings_hub.ownership.store import OwnershipStore
from filings_hub.research_index import open_index
from filings_hub.testing.ownership_fixtures import insider_xml

DAY = date(2026, 9, 10)
HEADER = "CIK|Company Name|Form Type|Date Filed|Filename\n"


@pytest.fixture()
def store(tmp_path):
    storage = Storage(str(tmp_path))
    index = open_index(storage)
    try:
        yield OwnershipStore(index, storage)
    finally:
        index.close()


def daily(*numbers):
    return HEADER + "\n".join(
        f"320193|Synthetic company|4|2026-09-10|edgar/data/320193/0000320193-26-{n:06d}.txt" for n in numbers
    )


def transport(text, *, fail_index=False, bad_accession=None):
    def handle(request):
        path = request.url.path
        if "daily-index" in path:
            return httpx.Response(404 if fail_index else 200, text=text)
        if path.endswith("-index.htm"):
            return httpx.Response(
                200,
                text='<table class="tableFile"><tr><td>1</td><td>Ownership</td><td><a href="/xsl/primary.xml">primary.xml</a></td><td>4</td><td>200</td></tr></table>',
            )
        if path.endswith("primary.xml"):
            return httpx.Response(
                200, content=b"<invalid" if bad_accession and bad_accession in path else insider_xml()
            )
        raise AssertionError(f"Unexpected request {request.url}")

    return EdgarClient(
        "Fixture fixture@example.com",
        requests_per_second=1000,
        max_retries=0,
        throttle_retries=0,
        transport=httpx.MockTransport(handle),
    )


def test_bounded_queue_resumes_without_losing_date_and_retry_is_idempotent(store):
    with transport(daily(1, 2)) as client:
        result = sync_ownership(store, client, until=DAY, max_filings=1)
        assert result["parsed"] == 1
        assert store.coverage()["pending"] == 1
        assert store.get_state("discovery:forward")["next_date"] == "2026-09-11"
        result = sync_ownership(store, client, until=DAY, max_filings=1)
        assert result["discovered"] == 0 and result["parsed"] == 1
        assert store.coverage()["parsed_filings"] == 2
        meta = filing_metadata(320193, "0000320193-26-000001", "4", str(DAY))
        assert process_filing(store, client, meta)["inserted"] is False
        assert len(store.index.query("SELECT id FROM ownership_filings")) == 2


def test_index_unavailable_keeps_cursor_and_existing_queue_still_drains(store):
    store.register_filing(filing_metadata(320193, "0000320193-26-000001", "4", str(DAY)))
    with transport("", fail_index=True) as client:
        result = sync_ownership(store, client, until=DAY)
    assert result["status"] == "partial" and result["parsed"] == 1
    assert store.get_state("discovery:forward")["next_date"] == str(DAY)


def test_registration_interruption_replays_whole_date(store, monkeypatch):
    original = store.register_filing

    def interrupted(metadata):
        if metadata["accession"].endswith("000002"):
            raise RuntimeError("Simulated database interruption")
        return original(metadata)

    monkeypatch.setattr(store, "register_filing", interrupted)
    with transport(daily(1, 2)) as client:
        result = sync_ownership(store, client, until=DAY)
        assert result["status"] == "partial"
        assert store.get_state("discovery:forward")["next_date"] == str(DAY)
        monkeypatch.setattr(store, "register_filing", original)
        assert sync_ownership(store, client, until=DAY)["parsed"] == 1
        assert store.coverage()["parsed_filings"] == 2


def test_bad_xml_does_not_discard_other_filings_and_notice_is_not_zero_holdings(store):
    with transport(daily(1, 2), bad_accession="000032019326000001") as client:
        result = sync_ownership(store, client, until=DAY)
        assert result["failed"] == 1 and result["parsed"] == 1
        meta = filing_metadata(9000900, "0000320193-26-000003", "13F-NT", str(DAY))
        assert process_filing(store, client, meta)["status"] == "unsupported"
    assert store.coverage()["unsupported"] == 1
    assert store.coverage()["failed"] == 1
    assert len(store.pending()) == 1


def test_daily_dates_aliases_and_untrusted_identifiers():
    text = daily(1).replace("|4|", "|SC 13G/A|").replace("2026-09-10", "20260910")
    assert parse_index(text)[0]["form"] == "SCHEDULE 13G/A"
    assert parse_index(text)[0]["filed_date"] == str(DAY)
    with pytest.raises(ValueError):
        parse_index(text.replace("edgar/data/320193", "edgar/data/123"))
    with pytest.raises(ValueError):
        parse_index("SEC access denied")
    with pytest.raises(ValueError):
        filing_metadata(320193, "../secret", "4", str(DAY))


def test_document_size_limit_is_checked_while_streaming(monkeypatch):
    monkeypatch.setattr("filings_hub.ownership.ingest.MAX_DOCUMENT_BYTES", 10)
    with transport(daily(1)) as client, pytest.raises(ValueError, match="download limit"):
        fetch_documents(client, filing_metadata(320193, "0000320193-26-000001", "4", str(DAY)))


def test_operator_verified_no_index_day_is_explicit_and_auditable(store):
    store.set_state(f"skip-date:{DAY}", {"reason": "Verified SEC index not published"})
    with transport("", fail_index=True) as client:
        result = sync_ownership(store, client, until=DAY)
    assert result["status"] == "ok"
    assert store.get_state("discovery:forward")["next_date"] == "2026-09-11"
    assert store.get_state(f"skip-date:{DAY}")["reason"]
