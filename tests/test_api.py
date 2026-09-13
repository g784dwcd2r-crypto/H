import httpx
import pytest
from fastapi.testclient import TestClient

from filings_hub.api.app import create_app, form_label
from filings_hub.api.security import RateLimiter
from filings_hub.config import Settings
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx

H = {"X-API-Key": "k"}


def _app(storage: Storage, edgar: bool = True):
    settings = Settings(
        lake_root=storage.root,
        database_url="",
        api_key="k",
        api_rate_limit_per_minute=1000,
        sec_user_agent="",
        _env_file=None,
    )
    client = EdgarClient("Test test@example.com", transport=httpx.MockTransport(fx.edgar_document_handler))
    return create_app(settings, edgar_client=client if edgar else None)


@pytest.fixture()
def client(built_lake):
    app = _app(built_lake)
    with TestClient(app) as c:
        yield c
    app.state.db.close()


@pytest.fixture()
def client_rw(lake_copy):
    """Over a private lake copy: for endpoints that write (documents, subscriptions, requests)."""
    app = _app(lake_copy)
    with TestClient(app) as c:
        yield c, lake_copy
    app.state.db.close()


def test_auth_required(client):
    assert client.get("/search?q=apple").status_code == 401
    assert client.get("/search?q=apple", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/search?q=apple&api_key=k").status_code == 200
    assert client.get("/health").status_code == 200


def test_search(client):
    r = client.get("/search?q=apple", headers=H).json()
    assert r["results"][0]["cik"] == fx.APPLE
    assert client.get("/search?q=GOOG", headers=H).json()["results"][0]["cik"] == fx.TWO_TICKER
    assert client.get("/search?q=19617", headers=H).json()["results"][0]["name"].startswith("JPMorgan")
    assert client.get("/search?q=zzzz", headers=H).json()["results"] == []


def test_company_and_periods(client):
    r = client.get("/companies/AAPL", headers=H).json()
    assert r["company"]["cik"] == fx.APPLE and r["tickers"][0]["ticker"] == "AAPL"
    assert r["latest_period"]["period_label"] == "Q3 2026" and r["next_expected"]["period_label"] == "FY2026"
    p = client.get("/companies/320193/periods", headers=H).json()["periods"]
    labels = [x["period_label"] for x in p]
    assert labels[:3] == ["Q3 2026", "Q2 2026", "Q1 2026"]
    q2 = next(x for x in p if x["period_label"] == "Q2 2026")
    assert q2["statements_source"] == "facts_fallback" and q2["checks_passed"] is True
    assert q2["results_filing_index_url"].endswith("-index.htm") and q2["earnings_release_filing_index_url"]
    assert client.get("/companies/NOPE", headers=H).status_code == 404
    assert client.get("/companies/42", headers=H).status_code == 404


def test_filings_filters(client):
    r = client.get("/companies/320193/filings?form=8-K&from=2026-01-01&to=2026-06-30", headers=H).json()["filings"]
    assert [f["filed_date"] for f in r] == ["2026-04-30", "2026-01-29"]
    assert r[0]["label"] == "Current report"
    assert form_label("XYZ-1") == "XYZ-1"


def test_statements_and_export(client):
    g = client.get("/companies/320193/statements?periods=FY2025,Q2 2026", headers=H).json()
    assert [p["period_label"] for p in g["periods"]] == ["FY2025", "Q2 2026"]
    assert g["periods"][1]["is_provisional"] is True
    assert client.get("/companies/999999/statements", headers=H).status_code == 404
    x = client.get("/companies/AAPL/export.xlsx?limit=2", headers=H)
    assert x.status_code == 200 and x.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert x.headers["content-disposition"] == 'attachment; filename="AAPL-statements.xlsx"'
    assert client.get("/companies/999999/export.xlsx", headers=H).status_code == 404


def test_facts_endpoint(client):
    r = client.get(
        "/companies/320193/facts?concept=RevenueFromContractWithCustomerExcludingAssessedTax&history=true",
        headers=H,
    ).json()
    assert len([f for f in r["facts"] if f["period_end"] == "2024-09-28"]) == 2
    cur = client.get(
        "/companies/320193/facts?concept=RevenueFromContractWithCustomerExcludingAssessedTax&unit=USD",
        headers=H,
    ).json()
    assert all(f["is_current"] for f in cur["facts"])
    assert client.get(f"/companies/{fx.OLD}/facts?concept=Assets", headers=H).json()["facts"] == []


def test_rate_limit(built_lake):
    settings = Settings(
        lake_root=built_lake.root,
        database_url="",
        api_key="",
        api_rate_limit_per_minute=2,
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        assert c.get("/search?q=a").status_code == 200
        assert c.get("/search?q=a").status_code == 200
        r = c.get("/search?q=a")
        assert r.status_code == 429 and "Retry-After" in r.headers
    app.state.db.close()
    rl = RateLimiter(1)
    assert rl.check("x") == (True, 0) and rl.check("x")[0] is False


def test_metrics_and_quality_queue(client):
    m = client.get("/metrics", headers=H).json()
    assert m["totals"]["companies"] == len(fx.COMPANIES) and m["totals"]["filings_with_statements"] > 0
    assert m["runs"][0]["kind"] == "backfill" and m["runs"][0]["status"] == "ok"
    assert m["filings_per_day"] and all("filings" in d for d in m["filings_per_day"])
    fy = {c["fiscal_year"]: c for c in m["checks_by_fiscal_year"]}
    assert fy[2025]["pass_rate"] is not None and 0 < fy[2025]["pass_rate"] < 1  # Broken Books drags FY2025 down
    q = client.get("/quality/failed", headers=H).json()
    assert (
        q["total"] == 1
        and q["failed"][0]["cik"] == fx.BROKEN
        and q["failed"][0]["check_name"] == "assets_eq_liabilities_and_equity"
    )
    assert q["failed"][0]["name"] == "Broken Books Ltd" and q["failed"][0]["form"] == "10-K"
    assert client.get("/quality/failed?limit=1&offset=5", headers=H).json()["failed"] == []


def test_search_resolves_every_identifier(client):
    """Each identifier has its own indexable branch: name substring, primary ticker, secondary ticker, CIK."""

    def ciks(q):
        return [r["cik"] for r in client.get(f"/search?q={q}", headers=H).json()["results"]]

    assert ciks("apple") == [fx.APPLE]  # name substring
    assert ciks("aapl") == [fx.APPLE]  # primary ticker, case-insensitive
    assert ciks("AAP") == []  # tickers match exactly, never by prefix
    assert ciks("GOOG") == [fx.TWO_TICKER]  # secondary ticker, only in the tickers table
    assert ciks("320193") == [fx.APPLE]  # CIK
    assert ciks("  Apple  ") == [fx.APPLE]  # trimmed
    assert ciks("JPMORGAN") == [fx.JPM]  # name match is case-insensitive
    assert fx.OLD in ciks("old co")  # inactive companies are still findable
    assert ciks("zzzz") == []


def test_search_ranks_exact_ticker_first(client):
    # "Two Ticker Holdings" and "Broken Books" both exist; an exact ticker hit outranks a name hit.
    rows = client.get("/search?q=BRKN", headers=H).json()["results"]
    assert rows[0]["cik"] == fx.BROKEN
    assert client.get("/search?q=holdings", headers=H).json()["results"][0]["cik"] == fx.TWO_TICKER


def test_periods_carry_key_numbers(client):
    p = client.get("/companies/320193/periods", headers=H).json()["periods"]
    fy25 = next(x for x in p if x["period_label"] == "FY2025")
    assert fy25["metrics"]["revenue"] > 0 and fy25["metrics"]["eps_diluted"] > 0
    assert {"revenue", "net_income", "eps_diluted", "total_assets", "operating_cash_flow"} <= set(fy25["metrics"])
    assert fy25["metrics"]["gross_profit"] > 0 and fy25["metrics"]["buybacks"] > 0  # as reported, not presented
    q3 = next(x for x in p if x["period_label"] == "Q3 2026")  # no statements yet: nulls, not an error
    assert q3["metrics"]["revenue"] is None


def test_peers_same_industry_by_size(client):
    r = client.get("/companies/AAPL/peers", headers=H).json()
    assert r["sic"] == "3571" and all(p["cik"] != fx.APPLE for p in r["peers"])
    assert client.get("/companies/42/peers", headers=H).status_code == 404


def test_documents_endpoint_names_the_exhibits(client_rw):
    c, storage = client_rw
    r = c.get("/companies/320193/documents?limit=3", headers=H).json()
    assert r["fetch_enabled"] and r["failures"] == []
    labels = {a: [d["label"] for d in docs] for a, docs in r["documents"].items()}
    tenq = labels[fx.APPLE_FILINGS[-1]["acc"]] if fx.APPLE_FILINGS[-1]["form"] == "10-Q" else None
    assert any("Earnings release" in v for v in labels.values())
    assert all("EX-101.INS" not in v and "GRAPHIC" not in v for v in labels.values())  # support files hidden
    if tenq:
        assert tenq[0] == "Quarterly report"
    # explicit accessions, and support files on request
    acc = fx.APPLE_FILINGS[0]["acc"]
    r2 = c.get(f"/companies/320193/documents?accessions={acc}&all=true", headers=H).json()
    kinds = [d["kind"] for d in r2["documents"][acc]]
    assert kinds[0] == "primary" and "support" in kinds
    from filings_hub.lake import layout

    assert storage.exists(f"{layout.documents_cik_dir(fx.APPLE)}/part-0.parquet")


def test_document_reader_endpoint(client_rw):
    c, _ = client_rw
    acc = fx.APPLE_FILINGS[0]["acc"]
    r = c.get(f"/companies/320193/filings/{acc}/document", headers=H).json()
    assert r["form"] == "10-K" and r["filename"] == fx.APPLE_FILINGS[0]["doc"]
    assert "<script" not in r["html"] and any(t["title"].startswith("Item 7") for t in r["toc"])
    assert r["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/")
    assert c.get("/companies/320193/filings/0000320193-99-000001/document", headers=H).status_code == 404
    assert c.get(f"/companies/320193/filings/{acc}/document?file=../x", headers=H).status_code == 404
    assert c.get(f"/companies/320193/filings/{acc}/document?file=nope.htm", headers=H).status_code == 502


def test_text_search_inside_filings(client_rw):
    c, _ = client_rw
    r = c.get("/companies/AAPL/search?q=buyback&filings=6", headers=H).json()
    assert r["searched"] > 0 and r["results"]
    forms = {x["form"] for x in r["results"]}
    assert "10-K" in forms or "10-Q" in forms
    release = [x for x in r["results"] if x["label"] == "Earnings release"]
    assert release and release[0]["filename"].endswith("ex991.htm") and release[0]["hits"][0]["match"] == "buyback"
    assert r["results"] == sorted(r["results"], key=lambda x: x["filed_date"], reverse=True)
    assert c.get("/companies/AAPL/search?q=zzzz-not-there", headers=H).json()["results"] == []
    assert c.get("/companies/AAPL/search?q=b", headers=H).status_code == 422


def test_recent_filings_for_a_watchlist(client):
    r = client.get(f"/filings/recent?ciks={fx.APPLE},{fx.JPM},abc&since=2026-01-01", headers=H).json()
    assert r["filings"] and {f["cik"] for f in r["filings"]} <= {fx.APPLE, fx.JPM}
    assert r["filings"][0]["filed_date"] >= r["filings"][-1]["filed_date"]
    results_8k = next(f for f in r["filings"] if f["form"] == "8-K" and "2.02" in (f["items"] or []))
    assert results_8k["is_results"] is True and results_8k["name"] and results_8k["label"] == "Current report"
    other_8k = next(f for f in r["filings"] if f["form"] == "8-K" and "2.02" not in (f["items"] or []))
    assert other_8k["is_results"] is False
    assert client.get("/filings/recent?ciks=abc", headers=H).json() == {"filings": []}
    assert client.get(f"/filings/recent?ciks={fx.APPLE}&since=2099-01-01", headers=H).json() == {"filings": []}


def test_subscriptions_and_requests(client_rw, monkeypatch):
    c, storage = client_rw
    r = c.post("/subscriptions", json={"email": "Me@Example.com", "ciks": [fx.APPLE, "19617"]}, headers=H)
    assert r.status_code == 200 and r.json() == {"stored": True, "email": "me@example.com", "ciks": 2}
    from filings_hub.ingest.digest import load_subscriptions

    assert load_subscriptions(storage)[0]["ciks"] == sorted([fx.APPLE, fx.JPM])
    assert c.post("/subscriptions", json={"email": "nope", "ciks": [1]}, headers=H).status_code == 422
    assert c.post("/subscriptions", json={"email": "a@b.co", "ciks": []}, headers=H).status_code == 422
    q = c.post("/requests", json={"region": "UK", "note": "Please add Tesco", "email": ""}, headers=H)
    assert q.status_code == 200 and q.json()["stored"]
    assert c.post("/requests", json={"region": "UK"}, headers=H).status_code == 422
    # a read-only lake answers 503, not a crash
    monkeypatch.setattr(Storage, "write_text", lambda *a, **k: (_ for _ in ()).throw(PermissionError("ro")))
    assert c.post("/subscriptions", json={"email": "a@b.co", "ciks": [1]}, headers=H).status_code == 503
