"""A machine-readable source register. Unconnected content is never shown as available."""

from typing import Any

from fastapi import Depends, FastAPI

SOURCE_REGISTER = [
    {
        "source_id": "sec-edgar",
        "name": "SEC EDGAR",
        "family": "public_filings",
        "status": "implemented",
        "geography": ["US regulatory filings, including registered foreign issuers"],
        "coverage_basis": "Serving-lake inventory; document indexing reports its own completeness.",
        "required_operations": ["store", "display", "search", "export"],
        "rights_note": "Public SEC access is not a blanket license for every third-party exhibit or downstream use.",
        "reference_url": "https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data",
    },
    {
        "source_id": "sec-fsds",
        "name": "SEC Financial Statement Data Sets",
        "family": "financial_statements",
        "status": "implemented",
        "geography": ["SEC structured filings"],
        "coverage_basis": "Loaded FSDS quarters and provisional company-facts fallback; see per-cell sources.",
        "required_operations": ["store", "display", "export"],
        "rights_note": "Source attribution and methodology are retained with exported values.",
        "reference_url": "https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets",
    },
    *[
        {
            "source_id": source,
            "name": name,
            "family": family,
            "status": "provider_required",
            "geography": [],
            "coverage_basis": "No production feed connected.",
            "required_operations": ["store", "display", "search", "ai", "export", "offline"],
            "rights_note": "Each required operation must be approved in the provider agreement before enablement.",
            "reference_url": None,
        }
        for source, name, family in [
            ("global-regulatory", "Additional regulator and exchange filings", "global_filings"),
            ("earnings-transcripts", "Earnings transcripts and audio", "transcripts"),
            ("licensed-news", "Licensed news", "news"),
            ("broker-research", "Broker and independent research", "research"),
            ("expert-research", "Expert interviews and channel checks", "experts"),
            ("market-consensus", "Prices, corporate actions and estimates", "market_data"),
            ("private-markets", "Private companies, funding and transactions", "private_markets"),
        ]
    ],
]


def attach_catalog_routes(app: FastAPI, *, database, auth) -> None:
    @app.get("/platform/sources")
    def sources(_: str = Depends(auth)) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "sources": SOURCE_REGISTER,
            "note": "Implemented means software support; it does not certify coverage or production operation.",
        }

    @app.get("/platform/publication")
    def publication(_: str = Depends(auth)) -> dict[str, Any]:
        if database.backend != "postgres":
            return {"backend": database.backend, "publication": None, "atomic_serving_publication": False}
        rows = database.query(
            "SELECT publication_id, kind, published_at, counts, all_periods "
            "FROM serving_publications ORDER BY published_at DESC LIMIT 1"
        )
        return {"backend": "postgres", "publication": rows[0] if rows else None, "atomic_serving_publication": True}
