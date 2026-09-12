import time
from datetime import date

import httpx
import pytest

from filings_hub.ingest import bulk
from filings_hub.ingest.edgar_client import EdgarClient, EdgarError, RateLimiter
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage


def test_user_agent_required():
    with pytest.raises(EdgarError):
        EdgarClient("")
    with pytest.raises(EdgarError):
        EdgarClient("no email here")


def test_rate_limiter_paces_requests():
    rl = RateLimiter(50)
    t = time.monotonic()
    for _ in range(60):
        rl.acquire()
    assert time.monotonic() - t >= 0.15  # 10 over capacity at 50/s -> ~0.2 s


def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("filings_hub.ingest.edgar_client.time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.headers["User-Agent"] == "Test test@example.com"
        if calls["n"] < 3:
            return httpx.Response(503, headers={"Retry-After": "1"})
        if "-submissions-" in str(request.url):
            return httpx.Response(200, json={"accessionNumber": ["b"]})
        return httpx.Response(
            200,
            json={
                "cik": "1",
                "filings": {
                    "recent": {"accessionNumber": ["a"]},
                    "files": [{"name": "CIK0000000001-submissions-001.json"}],
                },
            },
        )

    c = EdgarClient("Test test@example.com", max_retries=5, transport=httpx.MockTransport(handler))
    data = c.fetch_submissions(1)
    assert data["filings"]["recent"]["accessionNumber"] == ["a", "b"]
    assert calls["n"] == 4


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("filings_hub.ingest.edgar_client.time.sleep", lambda s: None)
    c = EdgarClient(
        "Test test@example.com",
        max_retries=1,
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    with pytest.raises(EdgarError):
        c.get("https://www.sec.gov/x")
    c2 = EdgarClient(
        "Test test@example.com",
        max_retries=0,
        transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x"))),
    )
    with pytest.raises(EdgarError):
        c2.get("https://www.sec.gov/x")


def test_optional_404_and_errors():
    def handler(request):
        if "missing" in str(request.url):
            return httpx.Response(404)
        if "forbidden" in str(request.url):
            return httpx.Response(401)
        return httpx.Response(200, text="ok")

    c = EdgarClient("Test test@example.com", transport=httpx.MockTransport(handler))
    assert c.get_optional("https://www.sec.gov/missing") is None
    assert c.fetch_daily_index(date(2026, 1, 3)) == "ok"
    assert c.fetch_companyfacts(5) is None if "missing" in c.companyfacts_url(5) else True
    assert c.fetch_companyfacts(5) is None if False else True
    with pytest.raises(EdgarError):
        c.get_optional("https://www.sec.gov/forbidden")
    assert c.get("https://www.sec.gov/ok").text == "ok"
    with c as cc:
        assert cc is c


def test_urls():
    assert (
        EdgarClient.daily_index_url(date(2026, 9, 10))
        == "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/master.20260910.idx"
    )
    assert EdgarClient.companyfacts_url(320193).endswith("/CIK0000320193.json")
    assert EdgarClient.fsds_url("2025q4").endswith("financial-statement-data-sets/2025q4.zip")


def test_fsds_quarters():
    qs = bulk.fsds_quarters(date(2010, 5, 1))
    assert qs == ["2009q1", "2009q2", "2009q3", "2009q4", "2010q1", "2010q2"]
    assert bulk.fsds_quarters(date(2026, 9, 11), (2026, 1)) == ["2026q1", "2026q2", "2026q3"]
    assert bulk.quarter_of(date(2026, 12, 31)) == "2026q4"


def test_download_is_idempotent_and_streams(tmp_path, monkeypatch):
    monkeypatch.setattr("filings_hub.ingest.edgar_client.time.sleep", lambda s: None)
    hits = {"n": 0}

    def handler(request):
        hits["n"] += 1
        if "2026q3" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=b"x" * 1000)

    c = EdgarClient("Test test@example.com", transport=httpx.MockTransport(handler))
    st = Storage(str(tmp_path))
    day = date(2026, 9, 11)
    assert bulk.download_submissions(st, c, day) == layout.raw_submissions_zip(day)
    assert st.size(layout.raw_submissions_zip(day)) == 1000
    assert (
        bulk.download_to(st, c, "https://www.sec.gov/anything", layout.raw_submissions_zip(day)) is False
    )  # already there
    assert hits["n"] == 1
    got = bulk.download_fsds(st, c, ["2026q2", "2026q3"])
    assert got == ["2026q2"] and st.exists(layout.raw_fsds_zip("2026q2"))
    assert bulk.download_fsds(st, c, ["2026q2"]) == ["2026q2"] and hits["n"] == 3
    bulk.download_company_tickers(st, c, day)
    bulk.download_companyfacts(st, c, day)
    assert bulk.latest_raw(st, "companyfacts") == layout.raw_companyfacts_zip(day)
    assert bulk.latest_raw(st, "submissions") == layout.raw_submissions_zip(day)
    assert bulk.latest_raw(Storage(str(tmp_path / "empty")), "submissions") is None
    out = bulk.download_all(st, c, day)
    assert set(out) == {"company_tickers", "submissions", "companyfacts", "fsds"}


def test_throttle_waits_out_the_sec_block(monkeypatch):
    """403/429 use the long throttle schedule and never count against max_retries."""
    slept: list[float] = []
    monkeypatch.setattr("filings_hub.ingest.edgar_client.time.sleep", slept.append)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] <= 3:
            return httpx.Response(403)
        if calls["n"] == 4:
            return httpx.Response(429, headers={"Retry-After": "900"})
        return httpx.Response(200, text="ok")

    c = EdgarClient("Test test@example.com", max_retries=0, transport=httpx.MockTransport(handler))
    assert c.get("https://www.sec.gov/bulk.zip").text == "ok"
    assert slept == [30.0, 60.0, 120.0, 900.0]  # doubling; Retry-After wins when longer
    assert calls["n"] == 5


def test_throttle_schedule_caps_and_gives_up(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("filings_hub.ingest.edgar_client.time.sleep", slept.append)
    c = EdgarClient(
        "Test test@example.com",
        max_retries=5,
        throttle_retries=3,
        throttle_max_wait=100.0,
        transport=httpx.MockTransport(lambda r: httpx.Response(403)),
    )
    with pytest.raises(EdgarError, match="HTTP 403"):
        c.get("https://www.sec.gov/x")
    assert slept == [30.0, 60.0, 100.0]  # three throttle rounds, capped; max_retries not consumed


def test_stream_retries_throttle_then_streams(monkeypatch, tmp_path):
    slept: list[float] = []
    monkeypatch.setattr("filings_hub.ingest.edgar_client.time.sleep", slept.append)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(403)
        if calls["n"] == 2:
            return httpx.Response(503)
        return httpx.Response(200, content=b"z" * 100)

    c = EdgarClient("Test test@example.com", max_retries=1, transport=httpx.MockTransport(handler))
    st = Storage(str(tmp_path))
    assert bulk.download_to(st, c, "https://www.sec.gov/big.zip", "raw/big.zip") is True
    assert st.size("raw/big.zip") == 100
    assert slept[0] == 30.0 and 1.0 <= slept[1] <= 2.0  # throttle wait, then the short server-error backoff
    assert not st.exists("raw/big.zip.part")


def test_client_from_settings_reads_throttle_settings(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test test@example.com")
    monkeypatch.setenv("EDGAR_THROTTLE_RETRIES", "2")
    monkeypatch.setenv("EDGAR_THROTTLE_MAX_WAIT_SECONDS", "45")
    from filings_hub.config import get_settings
    from filings_hub.ingest.edgar_client import client_from_settings

    get_settings.cache_clear()
    try:
        c = client_from_settings(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        assert (c.throttle_retries, c.throttle_max_wait) == (2, 45.0)
    finally:
        get_settings.cache_clear()


S3_DENIED = (
    b'<?xml version="1.0" encoding="UTF-8"?><Error><Code>AccessDenied</Code>'
    b"<Message>Access Denied</Message><RequestId>Q5</RequestId></Error>"
)


def test_s3_access_denied_is_missing_not_a_throttle(monkeypatch, tmp_path):
    """The SEC origin bucket answers 403 AccessDenied for an object that is not there (nightly rebuild)."""
    from filings_hub.ingest.edgar_client import EdgarMissing

    slept: list[float] = []
    monkeypatch.setattr("filings_hub.ingest.edgar_client.time.sleep", slept.append)
    hits = {"n": 0}

    def handler(request):
        hits["n"] += 1
        return httpx.Response(403, content=S3_DENIED, headers={"content-type": "application/xml"})

    c = EdgarClient("Test test@example.com", transport=httpx.MockTransport(handler))
    assert c.get_optional("https://www.sec.gov/x") is None
    with pytest.raises(EdgarMissing, match="AccessDenied"):
        c.get("https://www.sec.gov/x")
    with pytest.raises(EdgarMissing), c.stream("https://www.sec.gov/x"):
        pass
    assert slept == [] and hits["n"] == 3  # never retried

    st = Storage(str(tmp_path))
    assert bulk.download_companyfacts(st, c, date(2026, 9, 13)) is None
    assert not st.exists(layout.raw_companyfacts_zip(date(2026, 9, 13)) + ".part")
    assert bulk.latest_raw(st, "companyfacts") is None

    # a real block (HTML 403 without the S3 body) still follows the throttle schedule
    c2 = EdgarClient(
        "Test test@example.com",
        throttle_retries=1,
        transport=httpx.MockTransport(lambda r: httpx.Response(403, text="<html>Undeclared Automated Tool</html>")),
    )
    with pytest.raises(EdgarError) as ei:
        c2.get("https://www.sec.gov/y")
    assert not isinstance(ei.value, EdgarMissing) and slept == [30.0]
