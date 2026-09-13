import httpx
import pytest

from filings_hub.ingest import documents
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx


def client():
    return EdgarClient("Test test@example.com", transport=httpx.MockTransport(fx.edgar_document_handler))


def test_parse_filing_index_reads_the_table_and_unwraps_ix_links():
    f = fx.APPLE_FILINGS[0]  # the FY2024 10-K
    rows = documents.parse_filing_index(fx.filing_index_html(fx.APPLE, f))
    assert rows[0]["filename"] == f["doc"] and rows[0]["doc_type"] == "10-K" and rows[0]["seq"] == 1
    assert {r["doc_type"] for r in rows} >= {"EX-21.1", "EX-23.1", "EX-101.INS", "GRAPHIC"}
    assert documents.parse_filing_index("<html><body>no table</body></html>") == []


@pytest.mark.parametrize(
    "form,items,typ,desc,primary,expected",
    [
        ("10-K", [], "10-K", "10-K", True, ("Annual report", "primary")),
        ("10-K/A", [], "10-K/A", "", True, ("Annual report (amended)", "primary")),
        ("8-K", ["2.02", "9.01"], "EX-99.1", "Press Release", False, ("Earnings release", "release")),
        (
            "8-K",
            ["2.02", "9.01"],
            "EX-99.2",
            "Q3 Financial Data Supplement",
            False,
            ("Financial supplement", "supplement"),
        ),
        ("8-K", ["7.01"], "EX-99.1", "Investor Presentation", False, ("Investor presentation", "presentation")),
        ("8-K", ["7.01"], "EX-99.1", "Press release", False, ("Press release", "release")),
        ("8-K", ["2.02"], "8-K", "", True, ("8-K cover", "primary")),
        ("10-K", [], "EX-21.1", "Subsidiaries", False, ("Subsidiaries", "exhibit")),
        ("10-K", [], "EX-101.INS", "XBRL", False, ("EX-101.INS", "support")),
        ("DEF 14A", [], "DEF 14A", "", True, ("Proxy statement", "primary")),
    ],
)
def test_document_labels_are_plain_words(form, items, typ, desc, primary, expected):
    label, kind, rank = documents.label_document(form, items, typ, desc, primary)
    assert (label, kind) == expected and 0 <= rank <= 10


def test_ensure_documents_fetches_once_and_keeps_them(tmp_path):
    st = Storage(str(tmp_path))
    c = client()
    f = fx.APPLE_FILINGS[1]  # 8-K with 2.02
    filings = [{"accession": f["acc"], "form": f["form"], "items": f["items"].split(","), "primary_doc": f["doc"]}]
    table, failures = documents.ensure_documents(st, c, fx.APPLE, filings)
    assert failures == [] and st.exists(f"{layout.documents_cik_dir(fx.APPLE)}/part-0.parquet")
    labels = {r["doc_type"]: r["label"] for r in table.to_pylist()}
    assert labels["EX-99.1"] == "Earnings release" and labels["8-K"] == "8-K cover"
    release = next(r for r in table.to_pylist() if r["kind"] == "release")
    assert release["url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/") and release["rank"] == 1

    # second call: nothing to fetch (client None proves it), same rows back
    again, _ = documents.ensure_documents(st, None, fx.APPLE, filings)
    assert again.num_rows == table.num_rows

    # a filing whose index page is missing is a failure, not a crash; a read-only lake still serves
    missing = [{"accession": "0000320193-99-000001", "form": "10-K", "items": [], "primary_doc": "x.htm"}]
    t, fails = documents.ensure_documents(st, c, fx.APPLE, missing)
    assert t.num_rows == 0 and len(fails) == 1 and "404" in fails[0]


def test_ensure_documents_serves_from_memory_when_the_lake_is_read_only(tmp_path, monkeypatch):
    st = Storage(str(tmp_path))
    monkeypatch.setattr(
        Storage, "replace_dir_with_parquet", lambda *a, **k: (_ for _ in ()).throw(PermissionError("ro"))
    )
    f = fx.APPLE_FILINGS[0]
    filings = [{"accession": f["acc"], "form": f["form"], "items": [], "primary_doc": f["doc"]}]
    table, failures = documents.ensure_documents(st, client(), fx.APPLE, filings)
    assert failures == [] and table.num_rows > 0 and not st.exists(layout.documents_cik_dir(fx.APPLE))
