"""Public coverage measured from serving data, without account or operations records."""

from datetime import UTC, datetime
from typing import Any

from filings_hub.db.database import Database


def coverage_summary(db: Database) -> dict[str, Any]:
    totals = db.query(
        "SELECT (SELECT count(*) FROM companies) AS directory_companies, "
        "(SELECT count(DISTINCT cik) FROM statements) AS companies_with_statements, "
        "(SELECT count(*) FROM filings) AS filings, "
        "(SELECT count(DISTINCT accession) FROM statements) AS filings_with_statements, "
        "(SELECT max(filed_date) FROM filings) AS latest_filing_date"
    )[0]
    years = db.query(
        "SELECT fiscal_year, count(*) AS periods, "
        "sum(CASE WHEN statements_source = 'fsds' THEN 1 ELSE 0 END) AS structured, "
        "sum(CASE WHEN statements_source = 'facts_fallback' THEN 1 ELSE 0 END) AS provisional, "
        "sum(CASE WHEN statements_source IS NULL THEN 1 ELSE 0 END) AS unavailable, "
        "sum(CASE WHEN checks_passed = true THEN 1 ELSE 0 END) AS checks_passed, "
        "sum(CASE WHEN checks_passed = false THEN 1 ELSE 0 END) AS checks_failed, "
        "sum(CASE WHEN checks_passed IS NULL THEN 1 ELSE 0 END) AS checks_not_run "
        f"FROM {db.periods_table} GROUP BY fiscal_year ORDER BY fiscal_year DESC"
    )
    forms = db.query("SELECT form, count(*) AS filings FROM filings GROUP BY form ORDER BY filings DESC, form")
    last = db.query("SELECT max(finished_at) AS completed_at FROM run_log WHERE status = 'ok'")[0]
    return {
        "as_of": datetime.now(UTC).isoformat(),
        "jurisdiction": "SEC EDGAR (US filings, including foreign registrants)",
        "totals": totals,
        "fiscal_years": years,
        "forms": forms,
        "last_completed_ingestion": last["completed_at"],
        "limitations": [
            "A company in the directory does not imply complete financial statements or document coverage.",
            "Provisional statements come from company facts and can omit presentation detail.",
            "Arithmetic checks test selected accounting identities, not every number or disclosure.",
            "Latest comparative values can reflect reclassification as well as formal restatement.",
            "Coverage outside SEC EDGAR is not currently included.",
        ],
    }
