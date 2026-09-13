"""The gateway's service key must never become one shared budget for all website visitors."""

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from filings_hub.accounts import SessionSigner
from filings_hub.api.security import RateLimiter, make_auth


def call(auth, headers=None, host="192.0.2.1", query=b""):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/search",
            "query_string": query,
            "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
            "client": (host, 1000),
            "server": ("api", 8000),
            "scheme": "http",
        }
    )
    return asyncio.run(auth(request))


def limited(auth, headers=None, **kwargs):
    with pytest.raises(HTTPException) as exc:
        call(auth, headers, **kwargs)
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) > 0


def test_gateway_visitors_have_independent_allowances():
    auth = make_auth("service-key", RateLimiter(1))
    first = {"X-API-Key": "service-key", "X-Disclosure-Visitor": str(uuid4())}
    second = {"X-API-Key": "service-key", "X-Disclosure-Visitor": str(uuid4())}
    assert call(auth, first).startswith("visitor:")
    limited(auth, first)
    assert call(auth, second).startswith("visitor:")
    limited(auth, second)


def test_sessions_for_one_user_share_budget_across_visitors_and_devices():
    signer = SessionSigner("test-signing-secret", 1)
    auth = make_auth("service-key", RateLimiter(1), signer.verify)
    first = {"X-API-Key": "service-key", "X-Session": signer.sign("alice"), "X-Disclosure-Visitor": str(uuid4())}
    second = {**first, "X-Session": signer.sign("alice"), "X-Disclosure-Visitor": str(uuid4())}
    assert call(auth, first) == "user:alice"
    limited(auth, second, host="192.0.2.2")
    assert call(auth, {**second, "X-Session": signer.sign("bob")}) == "user:bob"


def test_forged_sessions_cannot_reset_a_visitors_budget():
    signer = SessionSigner("test-signing-secret", 1)
    auth = make_auth("service-key", RateLimiter(1), signer.verify)
    headers = {"X-API-Key": "service-key", "X-Disclosure-Visitor": str(uuid4()), "X-Session": "forged-one"}
    assert call(auth, headers).startswith("visitor:")
    limited(auth, {**headers, "X-Session": "forged-two"})


def test_service_auth_runs_before_trusting_identity_or_verifying_session():
    verified = []
    limiter = RateLimiter(1)
    auth = make_auth("service-key", limiter, lambda session: verified.append(session) or "fake")
    for key in [None, "wrong"]:
        headers = {"X-Disclosure-Visitor": str(uuid4()), "X-Session": "supplied"}
        if key:
            headers["X-API-Key"] = key
        with pytest.raises(HTTPException) as exc:
            call(auth, headers)
        assert exc.value.status_code == 401
    assert verified == []
    assert limiter.hits == {}


def test_direct_api_clients_are_limited_by_peer_not_shared_key():
    auth = make_auth("service-key", RateLimiter(1))
    assert call(auth, {"X-API-Key": "service-key"}) == "ip:192.0.2.1"
    limited(auth, {"X-API-Key": "service-key", "X-Forwarded-For": "spoofed"})
    assert call(auth, {"X-API-Key": "service-key"}, host="192.0.2.2") == "ip:192.0.2.2"


def test_untrusted_visitor_headers_in_dev_and_query_key_mode_are_ignored():
    dev = make_auth("", RateLimiter(1))
    assert call(dev, {"X-Disclosure-Visitor": str(uuid4())}) == "ip:192.0.2.1"
    limited(dev, {"X-Disclosure-Visitor": str(uuid4())})
    keyed = make_auth("service-key", RateLimiter(1))
    assert call(keyed, {"X-Disclosure-Visitor": str(uuid4())}, query=b"api_key=service-key") == "ip:192.0.2.1"
    limited(keyed, {"X-Disclosure-Visitor": str(uuid4())}, query=b"api_key=service-key")


def test_malformed_visitor_header_cannot_create_arbitrary_buckets():
    auth = make_auth("service-key", RateLimiter(1))
    assert call(auth, {"X-API-Key": "service-key", "X-Disclosure-Visitor": "chosen-by-caller"}) == "ip:192.0.2.1"
    limited(auth, {"X-API-Key": "service-key", "X-Disclosure-Visitor": "another-arbitrary-value"})


def test_expired_caller_buckets_are_reclaimed(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("filings_hub.api.security.time.monotonic", lambda: now[0])
    limiter = RateLimiter(1)
    assert limiter.check("old")[0]
    now[0] += 61
    assert limiter.check("new")[0]
    assert set(limiter.hits) == {"new"}
