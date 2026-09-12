"""Rate-limited, retrying HTTP client for SEC EDGAR.

SEC fair-access rules: max 10 requests/second and a descriptive User-Agent with contact details.
https://www.sec.gov/os/accessing-edgar-data
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import orjson

log = logging.getLogger(__name__)

WWW = "https://www.sec.gov"
DATA = "https://data.sec.gov"

SUBMISSIONS_BULK_URL = f"{WWW}/Archives/edgar/daily-index/bulkdata/submissions.zip"
COMPANYFACTS_BULK_URL = f"{WWW}/Archives/edgar/daily-index/bulkdata/companyfacts.zip"
COMPANY_TICKERS_EXCHANGE_URL = f"{WWW}/files/company_tickers_exchange.json"
COMPANY_TICKERS_URL = f"{WWW}/files/company_tickers.json"
FSDS_URL_TEMPLATE = f"{WWW}/files/dera/data/financial-statement-data-sets/{{quarter}}.zip"


class EdgarError(RuntimeError):
    pass


class RateLimiter:
    """Token bucket: at most `rate` requests per second, shared across threads."""

    def __init__(self, rate: float):
        self.rate = max(rate, 0.1)
        self.capacity = max(1.0, self.rate)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


class EdgarClient:
    RETRY_STATUSES = {403, 429, 500, 502, 503, 504}

    def __init__(
        self,
        user_agent: str,
        requests_per_second: float = 10.0,
        max_retries: int = 5,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        if not user_agent or "@" not in user_agent:
            raise EdgarError('SEC_USER_AGENT must look like "Company Name contact@email" (SEC fair-access policy).')
        self.user_agent = user_agent
        self.limiter = RateLimiter(requests_per_second)
        self.max_retries = max_retries
        headers = {
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "*/*",
        }
        self.http = httpx.Client(headers=headers, timeout=timeout, follow_redirects=True, transport=transport)

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> EdgarClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- core request with retry -------------------------------------------------------------
    def _request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        attempt = 0
        while True:
            self.limiter.acquire()
            try:
                resp = self.http.request(method, url, **kw)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                if attempt >= self.max_retries:
                    raise EdgarError(f"{method} {url} failed after {attempt + 1} attempts: {e}") from e
                self._backoff(attempt, url, str(e))
                attempt += 1
                continue
            if resp.status_code in self.RETRY_STATUSES and attempt < self.max_retries:
                self._backoff(attempt, url, f"HTTP {resp.status_code}", resp.headers.get("Retry-After"))
                attempt += 1
                continue
            return resp

    @staticmethod
    def _backoff(attempt: int, url: str, why: str, retry_after: str | None = None) -> None:
        delay = min(60.0, (2**attempt) + random.uniform(0, 1))
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        log.warning("EDGAR retry %s in %.1fs (%s): %s", attempt + 1, delay, why, url)
        time.sleep(delay)

    def get(self, url: str, **kw: Any) -> httpx.Response:
        resp = self._request("GET", url, **kw)
        if resp.status_code >= 400:
            raise EdgarError(f"GET {url} -> HTTP {resp.status_code}")
        return resp

    def get_optional(self, url: str) -> httpx.Response | None:
        """GET returning None on 404 (e.g. daily index for a weekend)."""
        resp = self._request("GET", url)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise EdgarError(f"GET {url} -> HTTP {resp.status_code}")
        return resp

    def get_json(self, url: str) -> Any:
        return orjson.loads(self.get(url).content)

    @contextmanager
    def stream(self, url: str) -> Iterator[httpx.Response]:
        """Streaming GET for large bulk files (retries only the connection phase)."""
        attempt = 0
        while True:
            self.limiter.acquire()
            try:
                with self.http.stream("GET", url) as resp:
                    if resp.status_code in self.RETRY_STATUSES and attempt < self.max_retries:
                        self._backoff(attempt, url, f"HTTP {resp.status_code}")
                        attempt += 1
                        continue
                    if resp.status_code >= 400:
                        raise EdgarError(f"GET {url} -> HTTP {resp.status_code}")
                    yield resp
                    return
            except (httpx.TransportError, httpx.TimeoutException) as e:
                if attempt >= self.max_retries:
                    raise EdgarError(f"stream {url} failed: {e}") from e
                self._backoff(attempt, url, str(e))
                attempt += 1

    # -- EDGAR endpoints ------------------------------------------------------------------------
    @staticmethod
    def submissions_url(cik: int) -> str:
        return f"{DATA}/submissions/CIK{cik:010d}.json"

    @staticmethod
    def submissions_page_url(name: str) -> str:
        return f"{DATA}/submissions/{name}"

    @staticmethod
    def companyfacts_url(cik: int) -> str:
        return f"{DATA}/api/xbrl/companyfacts/CIK{cik:010d}.json"

    @staticmethod
    def daily_index_url(day) -> str:
        q = (day.month - 1) // 3 + 1
        return f"{WWW}/Archives/edgar/daily-index/{day.year}/QTR{q}/master.{day.strftime('%Y%m%d')}.idx"

    @staticmethod
    def filing_index_url(cik: int, accession: str) -> str:
        return f"{WWW}/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm"

    @staticmethod
    def primary_doc_url(cik: int, accession: str, primary_doc: str) -> str:
        return f"{WWW}/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{primary_doc}"

    @staticmethod
    def fsds_url(quarter: str) -> str:
        return FSDS_URL_TEMPLATE.format(quarter=quarter)

    def fetch_submissions(self, cik: int) -> dict[str, Any]:
        """Company submissions JSON with all overflow pages merged into `filings.recent`."""
        data = self.get_json(self.submissions_url(cik))
        pages = (data.get("filings") or {}).get("files") or []
        recent = (data.get("filings") or {}).get("recent") or {}
        for page in pages:
            more = self.get_json(self.submissions_page_url(page["name"]))
            for k, v in more.items():
                if isinstance(v, list):
                    recent.setdefault(k, []).extend(v)
        data.setdefault("filings", {})["recent"] = recent
        return data

    def fetch_companyfacts(self, cik: int) -> dict[str, Any] | None:
        resp = self.get_optional(self.companyfacts_url(cik))
        return orjson.loads(resp.content) if resp is not None else None

    def fetch_daily_index(self, day) -> str | None:
        resp = self.get_optional(self.daily_index_url(day))
        return resp.text if resp is not None else None


def client_from_settings(transport: httpx.BaseTransport | None = None) -> EdgarClient:
    from filings_hub.config import get_settings

    s = get_settings()
    return EdgarClient(
        s.sec_user_agent,
        requests_per_second=s.edgar_requests_per_second,
        max_retries=s.edgar_max_retries,
        timeout=s.edgar_timeout_seconds,
        transport=transport,
    )
