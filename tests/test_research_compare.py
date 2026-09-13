from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from filings_hub.api.research import attach_research_search_routes
from filings_hub.db.database import Database
from filings_hub.lake.storage import Storage
from filings_hub.research_compare import MAX_INPUT_CHARACTERS, MAX_INPUT_LINES, compare_texts
from filings_hub.research_index import ResearchIndex


def record(text, version_id="sha256:before", doc_id="same-document"):
    return dict(
        document_id=doc_id,
        version_id=version_id,
        text_content=text,
        content_sha256=version_id,
        indexed_at="2026-09-13T10:00:00+00:00",
        source_url="https://www.sec.gov/Archives/example.htm",
    )


def seed_versions(index, storage, cik=9800000001):
    filing = dict(
        cik=cik,
        accession=f"{cik:010d}-26-000001",
        form="10-K",
        filed_date="2026-01-01",
        company_name="Synthetic Source Review",
    )
    index.register_filing(filing)
    doc_id = index.register_document(filing, {"filename": "filing.htm", "label": "Synthetic annual report"})
    before_text, after_text = "Heading\nRevenue was 100.\nEnd\n", "Heading\nRevenue was 90.\nEnd\n"
    before = index.add_version(storage, doc_id, before_text.encode(), before_text)
    after = index.add_version(storage, doc_id, after_text.encode(), after_text)
    return doc_id, before, after


def test_exact_text_changes_preserve_line_numbers_source_identity_and_whitespace():
    before = record("Heading\nRevenue was 100.\nEnd\n")
    after = record("Heading\nRevenue was 90.\nEnd\n", "sha256:after")
    result = compare_texts(before, after)
    assert result["complete"] and not result["text_identical"]
    assert result["before"]["version_id"] == "sha256:before"
    assert result["after"]["source_url"] == after["source_url"]
    assert result["total_hunks_in_compared_text"] == 1
    assert result["hunks"][0]["lines"] == [
        {"kind": "context", "before_line": 1, "after_line": 1, "text": "Heading\n"},
        {"kind": "delete", "before_line": 2, "after_line": None, "text": "Revenue was 100.\n"},
        {"kind": "insert", "before_line": None, "after_line": 2, "text": "Revenue was 90.\n"},
        {"kind": "context", "before_line": 3, "after_line": 3, "text": "End\n"},
    ]
    endings = compare_texts(record("risk\r\n"), record("risk\n"))
    assert not endings["text_identical"] and endings["hunks"][0]["lines"][0]["text"] == "risk\r\n"


def test_same_extracted_text_does_not_claim_identical_source_bytes():
    result = compare_texts(record("same", "different-source-bytes-1"), record("same", "different-source-bytes-2"))
    assert result["text_identical"] and result["complete"] and result["hunks"] == []
    assert result["before"]["content_sha256"] != result["after"]["content_sha256"]


def test_insert_at_start_and_delete_at_end_have_correct_zero_length_ranges():
    added = compare_texts(record("tail\n"), record("new\ntail\n"), context=0)["hunks"][0]
    assert added["before_start"] == 0 and added["before_count"] == 0
    assert added["after_start"] == 1 and added["after_count"] == 1
    deleted = compare_texts(record("head\nold\n"), record("head\n"), context=0)["hunks"][0]
    assert deleted["before_start"] == 2 and deleted["before_count"] == 1
    assert deleted["after_start"] == 1 and deleted["after_count"] == 0


def test_input_limits_are_explicit_even_when_only_the_uncompared_tail_changes():
    common = "same " * (MAX_INPUT_CHARACTERS // 5)
    result = compare_texts(record(common + "old tail"), record(common + "new tail"))
    assert not result["text_identical"] and not result["complete"]
    assert result["input_truncated"] and not result["output_truncated"]
    assert result["coverage"]["before_characters_compared"] == MAX_INPUT_CHARACTERS
    assert result["total_hunks_in_compared_text"] == 0
    common_lines = "same\n" * MAX_INPUT_LINES
    line_limited = compare_texts(record(common_lines + "old"), record(common_lines + "new"))
    assert line_limited["input_truncated"]
    assert line_limited["coverage"]["before_characters_compared"] == len(common_lines)


def test_hunk_and_output_limits_are_never_hidden():
    old = "old1\n" + "same\n" * 10 + "old2\n"
    new = "new1\n" + "same\n" * 10 + "new2\n"
    hunk_limited = compare_texts(record(old), record(new), context=0, max_hunks=1)
    assert hunk_limited["total_hunks_in_compared_text"] == 2 and len(hunk_limited["hunks"]) == 1
    assert hunk_limited["output_truncated"] and not hunk_limited["complete"]
    line_limited = compare_texts(record(old), record(new), context=0, max_lines=1)
    assert line_limited["output_truncated"] and line_limited["hunks"][0]["truncated"]
    assert sum(len(hunk["lines"]) for hunk in line_limited["hunks"]) == 1
    character_limited = compare_texts(record("a" * 60000), record("b" * 60000))
    assert character_limited["output_truncated"] and not character_limited["complete"]
    assert sum(len(line["text"]) for hunk in character_limited["hunks"] for line in hunk["lines"]) <= 100000


@pytest.mark.parametrize("options", [{"context": -1}, {"context": 11}, {"max_lines": 0}, {"max_hunks": 51}])
def test_invalid_diff_limits_fail(options):
    with pytest.raises(ValueError):
        compare_texts(record("old"), record("new"), **options)


def test_history_and_compare_api_checks_both_current_permissions_before_identity(tmp_path):
    storage = Storage(str(tmp_path / "lake"))
    index = ResearchIndex(path=tmp_path / "search.sqlite3")
    database = Database("", storage)
    doc_id, before, after = seed_versions(index, storage)
    other_doc, other_before, _other_after = seed_versions(index, storage, cik=9800000002)
    app = FastAPI()
    attach_research_search_routes(app, database=database, storage=storage, auth=lambda: "public", index=index)
    with TestClient(app) as client:
        history = client.get(f"/research/documents/{after}/history", params={"limit": 1}).json()
        assert history["total"] == 2 and history["next_offset"] == 1
        assert history["current_version_id"] == after and history["document_id"] == doc_id
        assert history["versions"][0]["version_id"] == after
        assert "text_content" not in history["versions"][0]
        second = client.get(f"/research/documents/{after}/history", params={"limit": 1, "offset": 1}).json()
        assert second["versions"][0]["version_id"] == before and second["next_offset"] is None
        diff = client.get("/research/compare", params={"before": before, "after": after})
        assert diff.status_code == 200 and diff.json()["complete"]
        assert diff.json()["after"]["version_id"] == after
        mismatch = client.get("/research/compare", params={"before": before, "after": other_before})
        assert mismatch.status_code == 422 and "same indexed document" in mismatch.json()["detail"]
        index.execute("UPDATE research_documents SET visibility='organization' WHERE document_id=?", [other_doc])
        restricted = client.get("/research/compare", params={"before": before, "after": other_before})
        missing = client.get("/research/compare", params={"before": before, "after": "sha256:" + "0" * 64})
        assert restricted.status_code == missing.status_code == 404 and restricted.json() == missing.json()
        assert client.get(f"/research/documents/{other_before}/history").status_code == 404
        index.execute("UPDATE research_documents SET source_id='restricted-provider' WHERE document_id=?", [doc_id])
        assert client.get("/research/compare", params={"before": before, "after": after}).status_code == 404
        assert client.get(f"/research/documents/{after}/history").status_code == 404
        assert client.get("/research/compare", params={"before": "bad", "after": after}).status_code == 422
    index.close()
    database.close()


def test_postgres_diff_history_parity_and_access_filters(pg_url, tmp_path):
    storage = Storage(str(tmp_path / "lake"))
    pg = ResearchIndex(database_url=pg_url)
    local = ResearchIndex(path=tmp_path / "search.sqlite3")
    cik = 9800000003
    try:
        for index in (pg, local):
            doc_id, before, after = seed_versions(index, storage, cik=cik)
        pg_diff, local_diff = pg.compare(before, after), local.compare(before, after)
        assert pg_diff["hunks"] == local_diff["hunks"]
        assert pg_diff["coverage"] == local_diff["coverage"] and pg_diff["complete"] == local_diff["complete"]
        assert pg.history(after)["total"] == local.history(after)["total"] == 2
        assert [v["version_id"] for v in pg.history(after)["versions"]] == [after, before]
        # Current document access alone must not expose a previously restricted capture.
        for index in (pg, local):
            metadata = json.loads(
                index.query("SELECT source_metadata FROM research_versions WHERE version_id=?", [before])[0][
                    "source_metadata"
                ]
            )
            metadata["visibility"] = "organization"
            index.execute(
                "UPDATE research_versions SET source_metadata=? WHERE version_id=?", [json.dumps(metadata), before]
            )
            assert index.compare(before, after) is None and index.version(before) is None
            assert index.history(after)["total"] == 1
        pg.execute("UPDATE research_documents SET visibility='organization' WHERE document_id=?", [doc_id])
        assert pg.compare(before, after) is None and pg.history(before) is None
    finally:
        pg.execute(
            "DELETE FROM research_terms WHERE version_id IN (SELECT version_id FROM research_versions WHERE document_id IN (SELECT document_id FROM research_documents WHERE cik=?))",
            [cik],
        )
        pg.execute(
            "DELETE FROM research_versions WHERE document_id IN (SELECT document_id FROM research_documents WHERE cik=?)",
            [cik],
        )
        pg.execute("DELETE FROM research_documents WHERE cik=?", [cik])
        pg.execute("DELETE FROM research_filings WHERE cik=?", [cik])
        pg.close()
        local.close()
