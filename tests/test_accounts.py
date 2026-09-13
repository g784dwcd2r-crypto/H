"""Accounts and the preference spine: stores, sessions, magic links, resolution, and the Phase A gate."""

from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from filings_hub import accounts as A
from filings_hub.api.app import create_app
from filings_hub.config import Settings
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx

H = {"X-API-Key": "k"}


def test_resolution_order_most_specific_wins():
    prefs = [
        A.Pref("global", "", "scale", "millions"),
        A.Pref("sector", "6021", "scale", "billions"),
        A.Pref("company", "19617", "scale", "thousands"),
        A.Pref("statement", "19617:CF", "scale", "units"),
        A.Pref("company", "320193", "periods_shown", 12),
        A.Pref("export", "profile-1", "layout", "per_statement"),  # export scope never resolves here
    ]
    r = A.resolve(prefs, cik=19617, sic="6021", statement="CF")
    assert r["scale"] == {"value": "units", "scope": "statement", "scope_key": "19617:CF", "source": "explicit"}
    assert A.resolve(prefs, cik=19617, sic="6021", statement="IS")["scale"]["value"] == "thousands"
    assert A.resolve(prefs, cik=1, sic="6021")["scale"]["value"] == "billions"
    assert A.resolve(prefs, cik=1, sic="9999")["scale"]["value"] == "millions"
    assert A.resolve([], cik=1)["scale"] == {
        "value": "millions",
        "scope": "default",
        "scope_key": "",
        "source": "default",
    }
    assert (
        A.resolve(prefs, cik=320193)["periods_shown"]["value"] == 12
        and A.resolve(prefs, cik=1)["periods_shown"]["value"] == 8
    )
    assert "layout" not in A.resolve(prefs, cik=1)  # an export-profile key has no default and does not apply
    assert A.resolve(prefs)["statement"]["value"] == "IS"  # no context at all still yields the defaults


def test_session_signer_round_trip_and_tamper():
    s = A.SessionSigner("secret", days=1)
    tok = s.sign("u1")
    assert s.verify(tok) == "u1"
    assert s.verify(tok[:-1] + ("0" if tok[-1] != "0" else "1")) is None
    assert s.verify(tok, now=time.time() + 2 * 86400) is None  # expired
    assert A.SessionSigner("other").verify(tok) is None and s.verify(None) is None and s.verify("v2.x.1.n.2") is None
    assert A.SessionSigner("").sign("u1")  # empty secret: still works for the process lifetime


def test_lake_store_users_tokens_prefs(tmp_path):
    st = A.LakeUserStore(Storage(str(tmp_path)))
    assert st.get_user_by_email("a@b.co") is None
    u = st.create_user("A@B.co")
    assert u.email == "a@b.co" and st.get_user(u.id) == u and st.get_user_by_email("a@b.co") == u
    token, link = A.issue_magic_link(st, "a@b.co", "https://hub.example")
    assert link == f"https://hub.example/auth/callback?token={token}"
    assert A.redeem_magic_link(st, "wrong") is None
    assert A.redeem_magic_link(st, token) == u
    assert A.redeem_magic_link(st, token) is None  # one use only
    st.put_pref(u.id, A.Pref("company", "320193", "scale", "thousands"))
    st.put_pref(u.id, A.Pref("company", "320193", "scale", "units"))  # overwrite, not duplicate
    st.put_pref(u.id, A.Pref("global", "", "scale", "millions"))
    assert sorted((p.scope, p.value) for p in st.list_prefs(u.id)) == [("company", "units"), ("global", "millions")]
    assert st.delete_pref(u.id, "company", "320193", "scale") and not st.delete_pref(u.id, "company", "320193", "scale")
    assert st.delete_all_prefs(u.id) == 1 and st.list_prefs(u.id) == []
    st.add_event(
        u.id,
        {
            "key": "scale",
            "scope": "global",
            "old": None,
            "new": "m",
            "source": "explicit",
            "at": "2026-09-13T00:00:00+00:00",
        },
    )


def test_postgres_store(pg_url):
    st = A.PostgresUserStore(pg_url)
    u = st.create_user(f"pg-{time.time_ns()}@example.com")
    assert st.get_user(u.id).email == u.email and st.get_user_by_email(u.email).id == u.id
    token, _ = A.issue_magic_link(st, u.email, "")
    assert A.redeem_magic_link(st, token).id == u.id and A.redeem_magic_link(st, token) is None
    st.put_pref(u.id, A.Pref("company", "320193", "scale", "thousands"))
    st.put_pref(u.id, A.Pref("company", "320193", "scale", {"nested": [1, 2]}))
    st.put_pref(u.id, A.Pref("global", "", "periods_shown", 12))
    prefs = {p.ident: p.value for p in st.list_prefs(u.id)}
    assert prefs[("company", "320193", "scale")] == {"nested": [1, 2]} and prefs[("global", "", "periods_shown")] == 12
    st.add_event(
        u.id,
        {
            "key": "scale",
            "scope": "company",
            "old": None,
            "new": "x",
            "source": "explicit",
            "at": "2026-09-13T00:00:00+00:00",
        },
    )
    assert st.delete_pref(u.id, "global", "", "periods_shown") and st.delete_all_prefs(u.id) == 1


def test_validate_pref():
    assert A.validate_pref("global", "", "scale", "m", "explicit") is None
    assert "scope_key" in A.validate_pref("global", "x", "scale", "m", "explicit")
    assert "scope_key" in A.validate_pref("company", "", "scale", "m", "explicit")
    assert A.validate_pref("nope", "", "scale", "m", "explicit")
    assert A.validate_pref("global", "", "bad key!", "m", "explicit")
    assert A.validate_pref("global", "", "scale", "m", "guess")
    assert A.validate_pref("global", "", "scale", "x" * 30000, "explicit")


def test_google_exchange_uses_verified_email():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com":
            assert b"code=abc" in req.content and b"client_id=cid" in req.content
            return httpx.Response(200, json={"access_token": "at"})
        assert req.headers["Authorization"] == "Bearer at"
        return httpx.Response(200, json={"email": "Person@Gmail.com", "email_verified": True})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert A.google_email_for_code("abc", "https://x/cb", "cid", "sec", http=http) == "person@gmail.com"
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "x"})))
    assert A.google_email_for_code("abc", "https://x/cb", "cid", "sec", http=bad) is None
    unverified = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"access_token": "t", "email": "a@b.co", "email_verified": False})
        )
    )
    assert A.google_email_for_code("abc", "https://x/cb", "cid", "sec", http=unverified) is None


@pytest.fixture()
def api(lake_copy):
    settings = Settings(
        lake_root=lake_copy.root,
        database_url="",
        api_key="k",
        api_rate_limit_per_minute=1000,
        sec_user_agent="",
        site_url="https://hub.example",
        session_secret="test-secret",
        auth_dev_links=True,
        _env_file=None,
    )
    client = EdgarClient("Test test@example.com", transport=httpx.MockTransport(fx.edgar_document_handler))
    app = create_app(settings, edgar_client=client)
    with TestClient(app) as c:
        yield c, app
    app.state.db.close()


def _sign_in(c: TestClient, email: str) -> dict:
    r = c.post("/auth/magic-link", json={"email": email}, headers=H)
    assert r.status_code == 200, r.text
    link = r.json()["dev_link"]
    token = link.split("token=")[1]
    v = c.post("/auth/verify", json={"token": token}, headers=H)
    assert v.status_code == 200, v.text
    return {**H, "X-Session": v.json()["session"]}


def test_phase_a_gate_thousands_here_millions_elsewhere_survives_a_new_session(api):
    """Set scale to thousands on one company, see millions elsewhere, close the browser, come back."""
    c, _app = api
    assert c.get("/me", headers=H).status_code == 401
    assert c.get("/auth/config", headers=H).json()["email_link"] is True
    hdr = _sign_in(c, "Analyst@Example.com")
    me = c.get("/me", headers=hdr).json()["user"]
    assert me["email"] == "analyst@example.com" and me["plan"] == "free"

    r = c.put(
        "/me/prefs", json={"scope": "company", "scope_key": "320193", "key": "scale", "value": "thousands"}, headers=hdr
    )
    assert r.status_code == 200 and r.json()["pref"]["source"] == "explicit"
    apple = c.get("/me/prefs/resolve?cik=320193&statement=IS", headers=hdr).json()["prefs"]
    jpm = c.get("/me/prefs/resolve?cik=19617", headers=hdr).json()["prefs"]
    assert apple["scale"] == {"value": "thousands", "scope": "company", "scope_key": "320193", "source": "explicit"}
    assert jpm["scale"]["value"] == "millions" and jpm["scale"]["scope"] == "default"
    assert apple["statement"]["value"] == "IS" and apple["periods_shown"]["value"] == 8

    # "close the browser, come back": a fresh sign-in (new session token) sees the same preferences
    hdr2 = _sign_in(c, "analyst@example.com")
    assert hdr2["X-Session"] != hdr["X-Session"]
    again = c.get("/me/prefs/resolve?cik=320193", headers=hdr2).json()["prefs"]
    assert again["scale"]["value"] == "thousands"
    assert c.get("/me", headers=hdr2).json()["user"]["id"] == me["id"]  # same account, not a new one

    # sector scope resolves through the company's SIC when only the CIK is given
    c.put("/me/prefs", json={"scope": "sector", "scope_key": "3571", "key": "periods_shown", "value": 12}, headers=hdr2)
    assert c.get("/me/prefs/resolve?cik=320193", headers=hdr2).json()["prefs"]["periods_shown"]["scope"] == "sector"

    # reset one, export, reset all, import
    assert c.delete("/me/prefs?scope=company&scope_key=320193&key=scale", headers=hdr2).json()["removed"] is True
    assert c.get("/me/prefs/resolve?cik=320193", headers=hdr2).json()["prefs"]["scale"]["scope"] == "default"
    exported = c.post("/me/prefs/export", headers=hdr2).json()
    assert exported["version"] == 1 and len(exported["prefs"]) == 1
    assert c.post("/me/prefs/reset", headers=hdr2).json()["removed"] == 1
    assert c.get("/me/prefs", headers=hdr2).json()["prefs"] == []
    assert (
        c.post("/me/prefs/import", json={"prefs": exported["prefs"] + [{"scope": "bad"}]}, headers=hdr2).json()[
            "imported"
        ]
        == 1
    )
    assert len(c.get("/me/prefs", headers=hdr2).json()["prefs"]) == 1


def test_auth_edge_cases(api):
    c, _app = api
    assert c.post("/auth/magic-link", json={"email": "nope"}, headers=H).status_code == 422
    assert c.post("/auth/verify", json={"token": "bogus"}, headers=H).status_code == 401
    assert c.get("/me", headers={**H, "X-Session": "v1.x.1.deadbeef"}).status_code == 401
    assert c.post("/auth/google", json={"code": "x", "redirect_uri": "y"}, headers=H).status_code == 503
    for _ in range(3):
        c.post("/auth/magic-link", json={"email": "burst@example.com"}, headers=H)
    assert c.post("/auth/magic-link", json={"email": "burst@example.com"}, headers=H).status_code == 429
    hdr = _sign_in(c, "edge@example.com")
    assert c.put("/me/prefs", json={"scope": "company", "key": "scale", "value": "x"}, headers=hdr).status_code == 422
    assert (
        c.put(
            "/me/prefs", json={"scope": "global", "key": "scale", "value": "x", "source": "magic"}, headers=hdr
        ).status_code
        == 422
    )
    assert c.delete("/me/prefs?scope=global&key=never", headers=hdr).json()["removed"] is False
    assert c.post("/me/prefs/import", json={"prefs": "no"}, headers=hdr).status_code == 422


def test_google_signin_endpoint(lake_copy):
    settings = Settings(
        lake_root=lake_copy.root,
        database_url="",
        api_key="k",
        api_rate_limit_per_minute=1000,
        sec_user_agent="",
        session_secret="s",
        google_client_id="cid",
        google_client_secret="sec",
        _env_file=None,
    )
    app = create_app(
        settings, edgar_client=EdgarClient("T t@e.com", transport=httpx.MockTransport(fx.edgar_document_handler))
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "at"})
        return httpx.Response(200, json={"email": "g@gmail.com", "email_verified": True})

    app.state.google_http = httpx.Client(transport=httpx.MockTransport(handler))
    with TestClient(app) as c:
        assert c.get("/auth/config", headers=H).json()["google_client_id"] == "cid"
        r = c.post("/auth/google", json={"code": "abc", "redirect_uri": "https://hub/auth/google/callback"}, headers=H)
        assert r.status_code == 200 and r.json()["user"]["email"] == "g@gmail.com"
        assert c.get("/me", headers={**H, "X-Session": r.json()["session"]}).json()["user"]["email"] == "g@gmail.com"
    app.state.db.close()
