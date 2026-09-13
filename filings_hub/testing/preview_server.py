"""Loopback-only synthetic data server for browser acceptance tests. Never uses a live lake."""

import os
from datetime import date
from pathlib import Path

import httpx
import uvicorn

from filings_hub.api.app import create_app
from filings_hub.config import Settings
from filings_hub.ingest.backfill import run_backfill
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx


def main() -> None:
    root = Path(os.environ.get("SMOKE_LAKE_ROOT", "work/browser-smoke-lake")).resolve()
    marker = root / ".synthetic-preview"
    if root.exists() and any(root.iterdir()) and not marker.exists():
        raise RuntimeError("Refusing to use a non-empty lake without the synthetic preview marker")
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text("Synthetic acceptance-test data only\n")
    storage = Storage(str(root))
    if not storage.exists("companies"):
        fx.seed_raw(storage, date(2026, 9, 11))
        run = run_backfill(storage, workers=1, skip_download=True, load_db=False, today=date(2026, 9, 11))
        if run.status != "ok":
            raise RuntimeError(run.summary())
    settings = Settings(
        lake_root=str(root),
        database_url="",
        api_key="preview",
        session_secret="local-preview-only",
        api_rate_limit_per_minute=10000,
        sec_user_agent="",
        site_url=os.environ.get("SMOKE_BASE_URL", "http://localhost:3100"),
        auth_dev_links=True,
        smtp_host="",
        admin_emails="admin@example.com",
        _env_file=None,
    )
    client = EdgarClient("Test test@example.com", transport=httpx.MockTransport(fx.edgar_document_handler))
    uvicorn.run(create_app(settings, edgar_client=client), host="127.0.0.1", port=8100)


if __name__ == "__main__":
    main()
