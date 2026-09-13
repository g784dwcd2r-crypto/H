"""API-key authentication and per-caller sliding-window limits behind the web gateway."""

from __future__ import annotations

import hmac
import re
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = {}
        self.lock = threading.Lock()
        self.last_sweep = time.monotonic()

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self.lock:
            # Visitor buckets expire; a busy public site must not retain every historic browser ID.
            if now - self.last_sweep > 60:
                self.hits = {ident: hits for ident, hits in self.hits.items() if hits and now - hits[-1] <= 60}
                self.last_sweep = now
            q = self.hits.setdefault(key, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False, int(60 - (now - q[0])) + 1
            q.append(now)
            return True, 0


VISITOR_HEADER = "x-disclosure-visitor"
VISITOR_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def make_auth(
    api_key: str,
    limiter: RateLimiter,
    verify_session: Callable[[str | None], str | None] | None = None,
):
    async def dependency(request: Request) -> str:
        header_key = request.headers.get("x-api-key") or ""
        provided = header_key or request.query_params.get("api_key") or ""
        if api_key and (not provided or not hmac.compare_digest(provided, api_key)):
            # Identity is considered only after the existing service-key gate succeeds.
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing API key (X-API-Key header)")

        uid = verify_session(request.headers.get("x-session")) if verify_session else None
        visitor = request.headers.get(VISITOR_HEADER, "")
        if uid:
            # Different sessions/devices for one signed-in person share their allowance.
            ident = f"user:{uid}"
        elif api_key and header_key and VISITOR_ID.fullmatch(visitor):
            # Only a key-authenticated gateway may assert its validated anonymous visitor cookie.
            # The web gateway generates this header; incoming browser headers never pass through.
            ident = f"visitor:{visitor}"
        else:
            # Direct API consumers keep independent peer-IP budgets, including development mode.
            # Do not trust X-Forwarded-For without a separately configured reverse-proxy trust policy.
            ident = f"ip:{request.client.host if request.client else 'anonymous'}"
        ok, retry = limiter.check(ident)
        if not ok:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "rate limit exceeded",
                headers={"Retry-After": str(retry)},
            )
        return ident

    return dependency
