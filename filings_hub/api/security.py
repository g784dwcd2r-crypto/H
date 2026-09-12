"""API-key auth and a per-key sliding-window rate limit (single tenant)."""

from __future__ import annotations

import hmac
import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self.lock:
            q = self.hits.setdefault(key, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False, int(60 - (now - q[0])) + 1
            q.append(now)
            return True, 0


def make_auth(api_key: str, limiter: RateLimiter):
    async def dependency(request: Request) -> str:
        provided = request.headers.get("x-api-key") or request.query_params.get("api_key") or ""
        if api_key:
            if not provided or not hmac.compare_digest(provided, api_key):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing API key (X-API-Key header)")
            ident = provided
        else:
            ident = request.client.host if request.client else "anonymous"
        ok, retry = limiter.check(ident)
        if not ok:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "rate limit exceeded",
                headers={"Retry-After": str(retry)},
            )
        return ident

    return dependency
