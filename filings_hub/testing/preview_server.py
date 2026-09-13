"""Loopback-only synthetic data server for browser acceptance tests. Never uses a live lake."""

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn

from filings_hub.api.app import create_app
from filings_hub.config import Settings
from filings_hub.ingest.backfill import run_backfill
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx


def seed_pagination_index(index, storage: Storage) -> None:
    """A fixed local-only cohort makes pagination acceptance independent of prior reader visits."""
    filing = {
        "cik": 320193,
        "accession": "0000320193-26-999999",
        "form": "8-K",
        "filed_date": "2026-01-01",
        "company_name": "Apple Inc. (synthetic pagination fixture)",
    }
    index.register_filing(filing)
    for number in range(25):
        doc_id = index.register_document(
            filing,
            {
                "filename": f"synthetic-pagination-{number:02d}.txt",
                "label": f"Synthetic pagination document {number + 1}",
            },
        )
        text = f"Disclosurepaginationfixture entry {number + 1}. Synthetic browser acceptance content only."
        index.add_version(storage, doc_id, text.encode(), text)
    index.inventory_status(filing["cik"], filing["accession"], "complete")


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
    from filings_hub.testing.research_provider import FixtureResearchProvider

    provider = FixtureResearchProvider()
    app = create_app(settings, edgar_client=client, research_provider=provider)
    # Populate the same durable index used by production, using only the mocked SEC transport.
    from filings_hub.research_index import open_index
    from filings_hub.research_ingest import discover_batch, index_documents_batch

    index = open_index(storage)
    discover_batch(app.state.db, storage, index, limit=500, client=client)
    index_documents_batch(storage, index, limit=500, client=client)
    # Preserve two explicit synthetic captures for the browser's evidence-history workflow.
    result = index.search('"share repurchase"', cik=320193, limit=1)["results"][0]
    current = index.version(result["version_id"])
    with storage.open(f"research/versions/{current['version_id'].split(':', 1)[1]}.bin") as stream:
        raw = stream.read()
    earlier_raw = raw.replace(b"Revenue grew year over year.", b"Revenue was unchanged year over year.")
    if earlier_raw == raw:
        raise RuntimeError("The synthetic document-history fixture did not create a text change")
    from filings_hub.research_ingest import extract

    text, pages = extract(earlier_raw, current["filename"])
    earlier = index.add_version(storage, current["document_id"], earlier_raw, text, pages)
    index.execute(
        "UPDATE research_versions SET indexed_at=? WHERE version_id=?",
        [(datetime.fromisoformat(current["indexed_at"]) - timedelta(minutes=1)).isoformat(), earlier],
    )
    index.add_version(storage, current["document_id"], raw, current["text_content"], current["pages"])
    seed_pagination_index(index, storage)
    from filings_hub.testing.ownership_fixtures import seed_ownership

    seed_ownership(index, storage)
    # Explicitly synthetic, stable documents exercise source quotes, counter-evidence and exact arithmetic.
    for suffix, source in [
        (
            "support",
            "disclosurecitedfixture. Synthetic test data only. Revenue was 1,200 and previous revenue was 1,000. Liquidity is adequate.",
        ),
        (
            "counter",
            "disclosurecitedfixture. Synthetic test data only. Contradictory evidence: liquidity may be insufficient during severe stress.",
        ),
    ]:
        doc = index.register_document(
            {"cik": 320193, "accession": "0000320193-26-990001", "form": "10-K", "filed_date": "2026-01-01"},
            {"filename": f"synthetic-research-{suffix}.txt", "title": f"Synthetic research {suffix}"},
        )
        index.add_version(storage, doc, source.encode(), source)
    from filings_hub.research_corpus import ResearchCorpus

    corpus = ResearchCorpus(index)
    while corpus.prepare(limit=100)["prepared_versions"]:
        pass
    while corpus.embed_batch(provider)["embedded_spans"]:
        pass
    index.close()
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("SMOKE_API_PORT", "8100")))


if __name__ == "__main__":
    main()
