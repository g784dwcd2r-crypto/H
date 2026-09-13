from __future__ import annotations

import io

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from filings_hub.api.research import attach_research_search_routes
from filings_hub.db.database import Database
from filings_hub.ingest.documents import document_url
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage
from filings_hub.research_index import ResearchIndex
from filings_hub.research_ingest import (
    ExtractionError,
    UnsupportedDocument,
    discover_batch,
    extract,
    index_documents_batch,
)
from filings_hub.research_query import QueryError, parse_query
from filings_hub.testing import edgar_fixtures as fx


def register(index, cik, filename="filing.htm", **changes):
    filing = dict(
        cik=cik, accession=f"{cik:010d}-26-000001", form="10-K", filed_date="2026-01-15", company_name=f"Company {cik}"
    )
    filing.update(changes)
    index.register_filing(filing)
    doc_id = index.register_document(filing, {"filename": filename, "label": "Annual report"})
    return filing, doc_id


@pytest.fixture
def corpus(tmp_path):
    storage = Storage(str(tmp_path / "lake"))
    index = ResearchIndex(path=tmp_path / "index.sqlite3")
    for cik, text, form in [
        (1, "Liquidity risk and debt covenant. Repurchase program approved.", "10-K"),
        (2, "Liquidity risk without a covenant. Dividends increased.", "10-Q"),
        (3, "Debt covenants and market risks. Share repurchase announced.", "8-K"),
    ]:
        _, doc_id = register(index, cik, form=form)
        index.add_version(storage, doc_id, text.encode(), text)
    yield index, storage
    index.close()


@pytest.mark.parametrize(
    "query,expected",
    [
        ("liquidity", [1, 2]),
        ("risk", [1, 2]),  # exact word, not 'risks'
        ('"debt covenant"', [1]),
        ("debt AND NOT covenant", [3]),
        ("repurchase OR dividends", [1, 2, 3]),
        ("(liquidity OR covenants) AND NOT dividends", [1, 3]),
        ("NOT (dividends OR covenants)", [1]),
        ("debt covenant", [1]),
        ("NOT NOT dividends", [2]),
        ('"missing words" OR dividends', [2]),
        ("' OR 1=1 --", None),
    ],
)
def test_boolean_words_phrases_negation_and_no_substring_matching(corpus, query, expected):
    index, _ = corpus
    if expected is None:
        with pytest.raises(QueryError):
            index.search(query)
    else:
        result = index.search(query)
        assert [r["cik"] for r in result["results"]] == expected
        assert result["total"] == len(expected)


@pytest.mark.parametrize(
    "query",
    [
        '"unclosed',
        "a AND",
        "OR a",
        "a)",
        "(a",
        "()",
        '""',
        "!!!",
        "a" * 1001,
        "NOT " * 15 + "risk",
        "non-GAAP",
        "risk OR OR debt",
    ],
)
def test_invalid_queries_fail_instead_of_reinterpreting(query):
    with pytest.raises(QueryError):
        parse_query(query)


def test_pagination_filters_empty_query_and_scope_counts(corpus):
    index, _ = corpus
    first = index.search("repurchase OR dividends", limit=2)
    assert first["total"] == 3 and first["next_offset"] == 2
    last = index.search("repurchase OR dividends", limit=2, offset=2)
    assert [r["cik"] for r in last["results"]] == [3] and last["next_offset"] is None
    assert index.search("liquidity", form="10-Q")["total"] == 1
    assert index.search("liquidity", cik=1)["coverage"]["indexed"] == 1
    assert index.search("liquidity", from_date="2026-02-01")["total"] == 0
    empty = index.search("")
    assert empty["total"] == 0 and empty["coverage"]["indexed"] == 3 and empty["coverage"]["partial"]
    with pytest.raises(ValueError):
        index.search("risk", limit=101)


def test_permissions_precede_counts_results_and_immutable_version_lookup(corpus):
    index, _ = corpus
    version = index.search("liquidity", cik=1)["results"][0]["version_id"]
    index.execute("UPDATE research_documents SET visibility='organization' WHERE cik=1")
    index.execute("UPDATE research_filings SET visibility='organization' WHERE cik=1")
    index.execute("UPDATE research_documents SET source_id='licensed-provider' WHERE cik=2")
    index.execute("UPDATE research_filings SET source_id='licensed-provider' WHERE cik=2")
    result = index.search("NOT nevermentioned")
    assert result["total"] == 1 and result["coverage"]["indexed"] == 1
    assert result["coverage"]["filings_known"] == 1
    assert index.version(version) is None
    with pytest.raises(ValueError, match="public SEC"):
        index.register_document({"cik": 3}, {"visibility": "organization", "filename": "secret.htm"})


def test_versions_are_durable_immutable_and_latest_only_in_search(tmp_path):
    storage = Storage(str(tmp_path / "lake"))
    path = tmp_path / "search.sqlite3"
    index = ResearchIndex(path=path)
    filing, doc_id = register(index, 1)
    old = index.add_version(storage, doc_id, b"Original number 100", "Original number 100")
    newer = index.add_version(storage, doc_id, b"Revised number 90", "Revised number 90")
    assert old != newer
    assert index.version(old)["text_content"] == "Original number 100"
    assert index.search("Original")["total"] == 0
    assert index.search("Revised")["results"][0]["version_id"] == newer
    index.register_document(filing, {"filename": "filing.htm", "label": "Edited inventory title"})
    assert index.add_version(storage, doc_id, b"Revised number 90", "Changed extractor output") == newer
    index.close()
    index = ResearchIndex(path=path)
    assert index.version(newer)["title"] == "Annual report"
    assert index.version(newer)["text_content"] == "Revised number 90"
    assert index.query("SELECT count(*) n FROM research_versions")[0]["n"] == 2
    index.close()


def test_phrase_after_16383_tokens_and_script_text_exclusion(corpus):
    index, storage = corpus
    _, doc_id = register(index, 4)
    raw = ("<script>secret phantomword</script><p>" + "word " * 17000 + "tail covenant</p>").encode()
    text, pages = extract(raw, "filing.htm")
    index.add_version(storage, doc_id, raw, text, pages)
    assert index.search('"tail covenant"')["total"] == 1
    assert index.search("phantomword")["total"] == 0


def make_pdf(text: str | None = "Liquidity covenant") -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if text:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_extraction_retains_real_page_offsets_and_fails_empty_pages():
    text, pages = extract(make_pdf(), "supplement.pdf")
    assert "Liquidity covenant" in text
    assert pages == [{"page": 1, "start": 0, "end": len(text)}]
    with pytest.raises(UnsupportedDocument, match="OCR or blank-page review"):
        extract(make_pdf(None), "scanned.pdf")
    with pytest.raises(UnsupportedDocument):
        extract(b"image", "figure.jpg")
    with pytest.raises(ExtractionError, match="no extractable text"):
        extract(b"<html><script>onlycode</script></html>", "empty.html")


def test_pending_unsupported_failed_and_retries_are_counted(corpus):
    index, storage = corpus
    filing, _missing = register(index, 4)
    _, _bad = register(index, 5, "bad.pdf")
    _, _graphic = register(index, 6, "image.jpg")
    storage.write_bytes(layout.raw_document(5, "0000000005-26-000001", "bad.pdf"), b"not a PDF")
    counts = index_documents_batch(storage, index, limit=20)
    assert counts == {"attempted": 3, "indexed": 0, "failed": 1, "pending": 1, "unsupported": 1}
    coverage = index.coverage()
    assert coverage["total"] == 6 and coverage["failed"] == 1 and coverage["pending"] == 1
    assert coverage["unsupported"] == 1 and coverage["partial"]
    storage.write_bytes(layout.raw_document(4, filing["accession"], "filing.htm"), b"<p>Recovered source</p>")
    assert index_documents_batch(storage, index, limit=1)["indexed"] == 1
    assert index.search("Recovered")["total"] == 1


def test_discovery_verifies_whole_bundle_and_resumes_bounded_batches(lake_copy, tmp_path):
    database = Database("", lake_copy)
    index = ResearchIndex(path=tmp_path / "search.sqlite3")
    with EdgarClient("Test test@example.com", transport=httpx.MockTransport(fx.edgar_document_handler)) as client:
        first = discover_batch(database, lake_copy, index, limit=1, cik=fx.APPLE, client=client)
        assert first["filings_registered"] == 1 and first["next_cursor"]
        assert not first["discovery_complete"]
        second = discover_batch(database, lake_copy, index, limit=500, cik=fx.APPLE, client=client)
        assert second["discovery_complete"]
        assert index.coverage(cik=fx.APPLE)["inventories_complete"] > 1
        docs = index.query("SELECT filename FROM research_documents WHERE cik=?", [fx.APPLE])
        assert len(docs) > first["documents_registered"]
        # Include the entire bundle, including support files, not only cover + EX-99.1.
        assert any(r["filename"].endswith(".jpg") for r in docs)
        result = index_documents_batch(lake_copy, index, limit=500, cik=fx.APPLE, client=client)
        assert result["indexed"] > 0 and result["unsupported"] > 0
    index.close()
    database.close()


def test_api_reads_only_index_and_reports_bad_syntax(corpus, tmp_path, monkeypatch):
    index, storage = corpus
    database = Database("", storage)
    app = FastAPI()
    attach_research_search_routes(app, database=database, storage=storage, auth=lambda: "public", index=index)
    monkeypatch.setattr(Storage, "read_bytes", lambda *a: pytest.fail("A search must not read raw lake documents"))
    with TestClient(app) as client:
        assert client.get("/research/search").json()["coverage"]["indexed"] == 3
        response = client.get("/research/search", params={"q": '"debt covenant"'})
        hit = response.json()["results"][0]
        assert hit["source_url"] == document_url(1, "0000000001-26-000001", "filing.htm")
        version = client.get("/research/documents/" + hit["version_id"])
        assert version.json()["text_content"].startswith("Liquidity risk")
        assert "raw_path" not in version.json()
        assert client.get("/research/search", params={"q": "(risk"}).status_code == 422
        assert client.get("/research/search", params={"from": "2026-02-02", "to": "2025-01-01"}).status_code == 422
        assert client.get("/research/documents/nope").status_code == 404
    database.close()


def test_failed_remote_bundle_is_explicit_not_a_complete_inventory(lake_copy, tmp_path):
    database = Database("", lake_copy)
    index = ResearchIndex(path=tmp_path / "search.sqlite3")
    with EdgarClient(
        "Test test@example.com", transport=httpx.MockTransport(lambda request: httpx.Response(404))
    ) as client:
        result = discover_batch(database, lake_copy, index, limit=1, cik=fx.APPLE, client=client)
        assert result["filings_registered"] == 1
        coverage = index.coverage(cik=fx.APPLE)
        assert coverage["inventories_failed"] == 1 and coverage["inventories_complete"] == 0
        assert coverage["partial"]
    index.close()
    database.close()


def test_postgres_and_local_exact_query_parity(pg_url, tmp_path):
    storage = Storage(str(tmp_path / "lake"))
    pg = ResearchIndex(database_url=pg_url)
    local = ResearchIndex(path=tmp_path / "parity.sqlite3")
    ciks = [9900000001, 9900000002, 9900000003]
    try:
        for index in (pg, local):
            for cik, text in zip(
                ciks, ["credit risk and liquidity", "credit risks", "liquidity debt covenant"], strict=True
            ):
                _, doc_id = register(index, cik)
                index.add_version(storage, doc_id, text.encode(), text)
        for query in ['"credit risk"', "credit AND NOT risk", "liquidity OR risks", "NOT (credit OR risk)"]:
            actual = pg.search(query)
            expected = local.search(query)
            assert [(r["cik"], r["snippet"]) for r in actual["results"]] == [
                (r["cik"], r["snippet"]) for r in expected["results"]
            ]
            assert actual["total"] == expected["total"]
        indexes = pg.query("SELECT indexname FROM pg_indexes WHERE tablename='research_terms'")
        assert "research_terms_lookup_idx" in {r["indexname"] for r in indexes}
    finally:
        pg.execute(
            "DELETE FROM research_terms WHERE version_id IN (SELECT version_id FROM research_versions WHERE document_id IN (SELECT document_id FROM research_documents WHERE cik>=9900000001))"
        )
        pg.execute(
            "DELETE FROM research_versions WHERE document_id IN (SELECT document_id FROM research_documents WHERE cik>=9900000001)"
        )
        pg.execute("DELETE FROM research_documents WHERE cik>=9900000001")
        pg.execute("DELETE FROM research_filings WHERE cik>=9900000001")
        pg.close()
        local.close()
