"""Loopback admin acceptance fixture. Never uses real accounts, credentials or a live lake."""

import os
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import uvicorn

from filings_hub.api.app import create_app
from filings_hub.config import Settings
from filings_hub.ingest.backfill import run_backfill
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake.storage import Storage
from filings_hub.research_index import open_index
from filings_hub.research_ingest import discover_batch, index_documents_batch
from filings_hub.testing import edgar_fixtures as fx


def main():
    root = Path(os.environ.get("ADMIN_SMOKE_LAKE", "work/admin-browser-lake")).resolve()
    marker = root / ".synthetic-admin-preview"
    if root.exists() and any(root.iterdir()) and not marker.exists():
        raise RuntimeError("Refusing a non-empty store without the synthetic admin marker")
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text("Synthetic admin acceptance data only\n")
    storage = Storage(str(root))
    if not storage.exists("companies"):
        fx.seed_raw(storage, date(2026, 9, 11))
        run = run_backfill(storage, workers=1, skip_download=True, load_db=False, today=date(2026, 9, 11))
        if run.status != "ok":
            raise RuntimeError("Synthetic fixture build failed")
    origin = os.environ.get("ADMIN_SMOKE_BASE_URL", "http://localhost:3201")
    settings = Settings(
        lake_root=str(root),
        database_url="",
        api_key="admin-preview",
        session_secret="admin-local-fixture",
        platform_admin_enabled=True,
        platform_admin_environment="development",
        platform_admin_origin=origin,
        platform_admin_local_bootstrap=True,
        auth_dev_links=True,
        smtp_host="",
        sec_user_agent="",
        site_url=origin,
        api_rate_limit_per_minute=10000,
        _env_file=None,
    )
    client = EdgarClient("Fixture fixture@example.test", transport=httpx.MockTransport(fx.edgar_document_handler))
    app = create_app(settings, edgar_client=client)
    # Only this explicitly marked synthetic preview freezes campaign time. Session expiry stays real.
    app.state.launch.clock = lambda: datetime(2026, 9, 13, tzinfo=UTC).timestamp()
    store = app.state.platform_admin
    with store.transaction() as tx:
        exists = tx.get("platform_admins", "disclosure") is not None
        # A restarted acceptance fixture must not inherit registration pauses from its last smoke.
        if tx.get("platform_settings", "registration"):
            tx.delete("platform_settings", "registration")
    store.bootstrap("disclosure", "1234", local=True, recover=exists)
    user = app.state.users.create_user(
        "analyst-admin-smoke@example.test",
        {"first_name": "Ada", "last_name": "Analyst", "company": "Synthetic Research"},
    )
    with store.transaction() as tx:
        if tx.get("platform_controls", user.id):
            tx.delete("platform_controls", user.id)
    if not app.state.account_security.organizations(user.id):
        app.state.account_security.create_organization(user.id, "Synthetic Research Team")
    app.state.signer.sign(user.id, device_label="Synthetic analyst browser")
    index = open_index(storage)
    discover_batch(app.state.db, storage, index, limit=500, client=client)
    index_documents_batch(storage, index, limit=500, client=client)
    index.close()
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("ADMIN_SMOKE_API_PORT", "8201")))


if __name__ == "__main__":
    main()
