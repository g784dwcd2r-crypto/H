from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from filings_hub.api.ownership import attach_ownership_routes
from filings_hub.lake.storage import Storage
from filings_hub.ownership.store import OwnershipStore
from filings_hub.research_index import ResearchIndex

URL = "https://www.sec.gov/Archives/edgar/data/700/fixture.xml"


@pytest.fixture(params=["sqlite", "postgres"])
def ownership(request, tmp_path):
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    storage = Storage(str(tmp_path / "lake"))
    index = ResearchIndex(database_url=url, path=storage.full("research/search.sqlite3"))
    store = OwnershipStore(index, storage)
    if url:
        index.execute("TRUNCATE ownership_ingest_state CASCADE")
        index.execute("DELETE FROM ownership_security_mappings")
    yield store, index, storage, url
    index.close()


def insider(**values):
    return {
        "id": "row",
        "owner_cik": 200,
        "owner_name": "Synthetic Analyst",
        "issuer_cik": 100,
        "officer_title": "Chief Executive",
        "is_director": False,
        "is_officer": True,
        "is_ten_percent_owner": False,
        "security_title": "Common stock",
        "is_derivative": False,
        "ownership_form": "D",
        "nature_of_ownership": None,
        "transaction_date": "2026-02-01",
        "transaction_code": "P",
        "acquired_disposed": "A",
        "shares": "10",
        "price": "5.25",
        "owned_after": "110",
        "footnotes": [],
        "is_holding": False,
        **values,
    }


def position(**values):
    return {
        "cusip": "037833100",
        "issuer_name": "Synthetic Company",
        "security_title": "Common stock",
        "shares": "100",
        "share_type": "SH",
        "put_call": None,
        "value_usd": "1000.25",
        "discretion": "SOLE",
        "other_managers": None,
        "voting_sole": "100",
        "voting_shared": "0",
        "voting_none": "0",
        **values,
    }


def event(**values):
    return {
        "issuer_cik": 100,
        "issuer_name": "Synthetic Company",
        "cusip": "037833100",
        "cusips": ["037833100"],
        "security_title": "Common stock",
        "event_date": "2026-02-01",
        "reporting_people": [
            {"cik": 400, "name": "Synthetic Reporting Person", "shares": "9007199254740993", "percent": "10.02"}
        ],
        "purpose": "Synthetic test purpose",
        "contracts": None,
        "filing_category": "passive",
        "exhibits": [],
        **values,
    }


def parsed(kind="insiders", seq=1, filed="2026-02-02", period="2026-02-01", **values):
    filing = {
        "accession": f"0000000700-26-{seq:06d}",
        "filer_cik": 700,
        "filed_date": filed,
        "source_url": URL,
        "form": {"insiders": "4", "institutions": "13F-HR", "events": "SC13G"}[kind],
        "issuer_cik": None if kind == "institutions" else 100,
        "issuer_name": "Synthetic Company",
        "manager_cik": 700 if kind == "institutions" else None,
        "manager_name": "Synthetic Fund",
        "report_period": period,
        "is_amendment": False,
        "confidential_omitted": False,
        "warnings": [],
    }
    filing.update(values.pop("filing", {}))
    return {
        "kind": kind,
        "filing": filing,
        "insiders": [insider()] if kind == "insiders" else [],
        "positions": [position()] if kind == "institutions" else [],
        "event": event() if kind == "events" else None,
        **values,
    }


def ingest(store, data, raw=b"<synthetic>Original retained source</synthetic>"):
    return store.ingest(data, [{"filename": "fixture.xml", "source_url": URL, "content": raw}])


def mapping(store):
    return store.map_security("037833100", 100, "Common stock", URL)


def test_idempotent_versions_replay_failure_and_atomic_mapping_conflict(ownership):
    store, index, _, _ = ownership
    data = parsed()
    first = ingest(store, data)
    assert not ingest(store, data)["inserted"]
    revised = copy.deepcopy(data)
    revised["insiders"][0]["shares"] = "11"
    second = ingest(store, revised, b"<synthetic>Corrected source</synthetic>")
    assert first["filing_id"] != second["filing_id"]
    assert store.document(100, first["documents"][0]["document_id"])["rows"][0]["shares"] == "10"
    ingest(store, data)
    assert store.flow(100, "insiders")["items"][0]["transactions"][0]["shares"] == "11"
    store.record_failure(data["filing"], "Synthetic retry failed")
    assert store.flow(100, "insiders")["items"] and store.coverage(100)["failed"] == 1
    ingest(store, revised, b"<synthetic>Corrected source</synthetic>")
    assert store.coverage(100)["failed"] == 0
    store.map_security("037833100", 999, "Common stock", URL)
    before = index.query("SELECT count(*) n FROM ownership_filings")[0]["n"]
    with pytest.raises(ValueError, match="Conflicting CUSIP"):
        ingest(store, parsed("events", seq=2))
    assert index.query("SELECT count(*) n FROM ownership_filings")[0]["n"] == before
    assert index.query("SELECT issuer_cik FROM ownership_security_mappings")[0]["issuer_cik"] == 999


def test_insider_buckets_denominator_filters_zero_and_joint_clusters(ownership):
    store, _, _, _ = ownership
    ingest(
        store,
        parsed(
            seq=1,
            insiders=[insider(is_holding=True, shares=None, transaction_code=None, owned_after="100")],
            filing={"form": "3"},
        ),
    )
    ingest(store, parsed(seq=2, filed="2026-02-03", insiders=[insider(transaction_date="2026-02-02")]))
    ingest(
        store,
        parsed(
            seq=3,
            filed="2026-02-04",
            insiders=[insider(transaction_date="2026-02-03", transaction_code="A", shares="7", owned_after="117")],
        ),
    )
    buys = store.flow(100, "insiders", direction="buys", from_date="2026-02-01", to_date="2026-02-05")
    assert buys["total"] == 1 and buys["items"][0]["summary"] == "Purchase"
    assert buys["items"][0]["transactions"][0]["change_percent"] == "10.0000"
    assert len(buys["items"][0]["history"]) >= 2
    indirect = insider(
        transaction_date="2026-02-04", ownership_form="I", nature_of_ownership="Trust", shares=0, owned_after="9999"
    )
    ingest(store, parsed(seq=4, filed="2026-02-05", insiders=[indirect]))
    latest = store.flow(100, "insiders")["items"][0]
    assert latest["metrics"][0]["value"] == "0" and latest["history"] == []
    joint = [
        insider(owner_cik=value, joint_reporting=True, transaction_group_id="one-purchase") for value in [201, 202]
    ]
    ingest(store, parsed(seq=5, filed="2026-02-06", insiders=joint))
    cluster = store.flow(100, "insiders", from_date="2026-02-06", to_date="2026-02-06")["purchase_cluster"]
    assert cluster["unique_reporting_identities"] == 1
    assert store.flow(100, "insiders", direction="sales")["total"] == 0


def test_verified_mapping_and_adjacent_quarter_comparison_only(ownership):
    store, _, _, _ = ownership
    baseline = ingest(store, parsed("institutions", seq=1, filed="2026-05-01", period="2026-03-31"))
    assert store.flow(100, "institutions")["items"] == []
    assert store.coverage(100)["unmatched_positions"] == 1
    mapping(store)
    first = store.flow(100, "institutions")["items"][0]
    assert "First observed" in first["summary"] and first["history"] == []
    assert store.flow(700, "institutions")["items"] == []  # manager CIK is not subject issuer
    current = ingest(
        store,
        parsed(
            "institutions",
            seq=2,
            filed="2026-08-01",
            period="2026-06-30",
            positions=[position(shares="0", value_usd="0")],
        ),
    )
    card = store.flow(100, "institutions")["items"][0]
    assert card["summary"] == "Reduced reported position" and card["history"][1]["value"] == "0"
    assert card["metrics"][0]["value"] == "0"
    assert store.document(700, current["documents"][0]["document_id"]) is None
    assert store.document(100, baseline["documents"][0]["document_id"])["rows"][0]["shares"] == "100"


def test_absence_requires_clean_adjacent_evidence_not_confidential_or_gap(ownership):
    store, _, _, _ = ownership
    mapping(store)
    ingest(store, parsed("institutions", seq=1, filed="2026-05-01", period="2026-03-31"))
    current = ingest(
        store,
        parsed("institutions", seq=2, filed="2026-08-01", period="2026-06-30", positions=[position(cusip="594918104")]),
    )
    card = store.flow(100, "institutions")["items"][0]
    assert "No longer reported" in card["summary"] and "not a confirmed exit" in card["summary"]
    source = store.document(100, current["documents"][0]["document_id"])
    assert source["rows"] == [] and source["linkage"]["type"] == "adjacent_quarter_comparison"
    assert store.document(999, current["documents"][0]["document_id"]) is None
    ingest(
        store,
        parsed(
            "institutions",
            seq=3,
            filed="2026-08-02",
            period="2026-06-30",
            positions=[],
            filing={"is_amendment": True, "form": "13F-HR/A", "confidential_omitted": None},
        ),
    )
    assert "unknown" in store.flow(100, "institutions")["items"][0]["summary"]
    ingest(
        store,
        parsed("institutions", seq=4, filed="2027-02-01", period="2026-12-31", positions=[position(shares="200")]),
    )
    gap = store.flow(100, "institutions")["items"][0]
    assert not gap["history"] and "First observed" in gap["summary"]


def test_event_multiple_cusips_alias_metadata_notifications_and_source_isolation(ownership):
    store, _, _, _ = ownership
    data = parsed("events", event=event(cusip=None, cusips=["037833100", "594918104"]))
    store.register_filing(data["filing"])
    first = ingest(store, data)
    second = ingest(store, parsed("events", seq=2, filed="2026-02-03"))
    card = store.flow(100, "events", limit=1)
    assert card["total"] == 2 and card["next_offset"] == 1
    assert card["items"][0]["metrics"][0]["value"] == "9007199254740993"
    assert store.document(700, first["documents"][0]["document_id"]) is None
    assert store.document(100, first["documents"][0]["document_id"])["event"]["cusips"] == ["037833100", "594918104"]
    events = store.notification_events([100], "2026-02-01", "events", limit=1)
    later = store.notification_events([100], "2026-02-01", "events", limit=1, offset=1)
    assert len(events) == len(later) == 1 and events[0]["id"] != later[0]["id"]
    assert later[0]["accession"] == parsed("events", seq=2)["filing"]["accession"]
    assert first["filing_id"] != second["filing_id"]
    store.set_state("cursor", {"offset": 1})
    assert store.get_state("cursor") == {"offset": 1}


def test_pending_priority_failure_tail_and_atomic_publication(ownership, monkeypatch):
    store, index, _, _ = ownership
    older, newer = parsed(seq=1), parsed(seq=2)
    store.record_failure(older["filing"], "Failed earlier")
    pending = store.register_filing(newer["filing"])
    assert store.pending(limit=1)[0]["id"] != pending["id"]
    store.record_failure(older["filing"], "Retried and moved to tail")
    assert store.pending(limit=1)[0]["id"] == pending["id"]
    before = index.query("SELECT count(*) n FROM ownership_filings")[0]["n"]
    write = store._persist_content

    def fail_normalized(path, content):
        if path.startswith("ownership/insiders/"):
            raise OSError("Synthetic publication failure")
        return write(path, content)

    monkeypatch.setattr(store, "_persist_content", fail_normalized)
    with pytest.raises(OSError):
        ingest(store, newer)
    assert index.query("SELECT count(*) n FROM ownership_filings")[0]["n"] == before
    assert store.flow(100, "insiders")["items"] == []


def test_concurrent_idempotent_ingest_on_distinct_connections(ownership):
    store, _, storage, url = ownership
    other_index = ResearchIndex(database_url=url, path=storage.full("research/search.sqlite3"))
    other = OwnershipStore(other_index, storage)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda item: ingest(item, parsed()), [store, other]))
        assert sum(row["inserted"] for row in results) == 1
    finally:
        other_index.close()


def app_for(index, storage, url=""):
    app = FastAPI()

    def auth(x_api_key: str = Header("")):
        if x_api_key != "test":
            raise HTTPException(401, "Denied")

    class Database:
        pass

    database = Database()
    database.url = url
    attach_ownership_routes(app, database=database, storage=storage, auth=auth, index=index)
    return app


def test_api_filters_exact_csv_and_subject_authorization(ownership):
    store, index, storage, url = ownership
    data = parsed(insiders=[insider(owner_name='=HYPERLINK("https://example.test")', shares="9007199254740993")])
    result = ingest(store, data)
    with TestClient(app_for(index, storage, url)) as client:
        headers = {"X-API-Key": "test"}
        assert client.get("/companies/100/ownership/insiders").status_code == 401
        assert client.get("/companies/100/ownership/institutions?direction=buys", headers=headers).status_code == 422
        assert (
            client.get("/companies/100/ownership/events?from=2026-03-01&to=2026-01-01", headers=headers).status_code
            == 422
        )
        assert client.get("/companies/100/ownership/insiders?limit=51", headers=headers).status_code == 422
        exported = client.get("/companies/100/ownership/insiders/export.csv", headers=headers)
        assert exported.status_code == 200 and "'=" in exported.text and "9007199254740993" in exported.text
        ident = result["documents"][0]["document_id"]
        assert client.get(f"/companies/700/ownership/documents/{ident}", headers=headers).status_code == 404
        assert (
            client.get(f"/companies/100/ownership/documents/{ident}", headers=headers)
            .json()["raw_text"]
            .startswith("<synthetic>")
        )
        assert client.get("/ownership/recent?ciks=100&flow=insiders", headers=headers).json()["flow"] == "insiders"


def test_read_routes_do_not_create_corpus_or_fetch(tmp_path):
    storage = Storage(str(tmp_path / "empty"))
    with TestClient(app_for(None, storage)) as client:
        assert client.get("/ownership/coverage", headers={"X-API-Key": "test"}).status_code == 503
    assert not Path(storage.full("research")).exists()


def test_cofiled_accession_is_one_observation_with_retained_provenance(ownership):
    store, index, _, _ = ownership
    data = parsed()
    first = ingest(store, data)
    alternate = copy.deepcopy(data)
    alternate["filing"]["filer_cik"] = 9000001
    alternate["filing"]["source_url"] = "https://www.sec.gov/Archives/edgar/data/9000001/fixture.xml"
    second = store.ingest(
        alternate,
        [
            {
                "filename": "fixture.xml",
                "source_url": alternate["filing"]["source_url"],
                "content": b"<synthetic>Original retained source</synthetic>",
            }
        ],
    )
    assert first["id"] == second["id"] and first["filing_id"] == second["filing_id"]
    assert not second["inserted"] and second["warnings"] == []
    assert len(store.flow(100, "insiders")["items"][0]["transactions"]) == 1
    assert len(store.notification_events([100], "2026-01-01", "insiders")) == 1
    provenance = json.loads(index.query("SELECT metadata FROM ownership_ingest_state")[0]["metadata"])
    assert len(provenance["source_aliases"]) == 2 and len(provenance["discovery_sources"]) == 2
    assert store.feed(list(range(1, 201)), "2026-01-01", "insiders")["total"] == 1
    assert len(store.notification_events(list(range(1, 201)), "2026-01-01", "insiders")) == 1


def test_truncated_source_is_repaired_and_corrupt_published_bytes_are_not_served(ownership):
    store, index, storage, url = ownership
    raw = b"<synthetic>Original retained source</synthetic>"
    raw_path = f"ownership/raw/{hashlib.sha256(raw).hexdigest()}.bin"
    storage.write_bytes(raw_path, b"truncated")
    result = ingest(store, parsed())
    assert storage.read_bytes(raw_path) == raw
    document_id = result["documents"][0]["document_id"]
    storage.write_bytes(raw_path, b"corrupt")
    with TestClient(app_for(index, storage, url)) as client:
        response = client.get(f"/companies/100/ownership/documents/{document_id}", headers={"X-API-Key": "test"})
        assert response.status_code == 503 and "corrupt" not in response.text
    assert not ingest(store, parsed())["inserted"]
    assert store.document(100, document_id)["raw_text"] == raw.decode()


def test_real_parser_sources_can_publish_without_identity_inference(ownership):
    from filings_hub.ownership.parse import parse_filing

    store, _, _, _ = ownership
    root = Path(__file__).parent / "fixtures/ownership"
    sources = json.loads((root / "real-sources.json").read_text())
    for source in sources:
        docs = [
            {
                "filename": row["filename"],
                "source_url": row["source_url"],
                "content": (root / row["fixture"]).read_bytes(),
            }
            for row in [source] + ([source["table"]] if source.get("table") else [])
        ]
        result = store.ingest(parse_filing(source["form"], docs, source), docs)
        assert result["status"] == "parsed"
    assert store.coverage()["parsed_filings"] == len(sources)
