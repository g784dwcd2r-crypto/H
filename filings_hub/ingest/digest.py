"""Email alerts: a subscriber follows some companies; each refresh mails the new results documents.

Subscriptions live in the lake as `subscriptions/{id}.json` ({email, ciks, created}); the API writes
them, the daily refresh reads them. One email per subscriber per run, only when something they follow
filed a results document (10-K, 10-Q, 20-F, 40-F, or an 8-K with item 2.02)."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from filings_hub.ingest.periods import RESULTS_FORMS, base_form
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)


def subscription_id(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def save_subscription(storage: Storage, email: str, ciks: list[int]) -> dict[str, Any]:
    rec = {
        "email": email.strip().lower(),
        "ciks": sorted({int(c) for c in ciks}),
        "created": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    storage.write_text(f"{layout.SUBSCRIPTIONS}/{subscription_id(email)}.json", json.dumps(rec))
    return rec


def load_subscriptions(storage: Storage) -> list[dict[str, Any]]:
    out = []
    for rel in storage.glob(f"{layout.SUBSCRIPTIONS}/*.json"):
        try:
            out.append(json.loads(storage.read_text(rel)))
        except Exception as e:
            log.warning("bad subscription %s: %s", rel, e)
    return out


def is_results_filing(row: dict[str, Any]) -> bool:
    form = base_form(row.get("form") or "")
    if form in RESULTS_FORMS:
        return True
    items = row.get("items") or []
    return form == "8-K" and any(str(i).startswith("2.02") for i in items)


def send_digests(
    storage: Storage,
    new_rows: list[dict[str, Any]],
    names: dict[int, str],
    sender: Callable[[str, str, str], bool] | None = None,
    site_url: str = "",
) -> int:
    """Mail every subscriber whose companies appear in `new_rows` (filing rows with cik, form, items,
    filed_date, accession, primary_doc_url). Returns the number of emails sent."""
    from filings_hub.ingest import alerts

    send = sender or alerts.send_email  # resolved at call time so tests and deployments can swap it
    results = [r for r in new_rows if is_results_filing(r)]
    if not results:
        return 0
    by_cik: dict[int, list[dict[str, Any]]] = {}
    for r in results:
        by_cik.setdefault(int(r["cik"]), []).append(r)
    sent = 0
    for sub in load_subscriptions(storage):
        mine = [r for c in sub.get("ciks", []) for r in by_cik.get(int(c), [])]
        if not mine:
            continue
        lines = []
        for r in sorted(mine, key=lambda x: (str(x.get("filed_date")), x["accession"])):
            name = names.get(int(r["cik"]), f"CIK {r['cik']}")
            what = "Earnings release (8-K)" if base_form(r.get("form") or "") == "8-K" else r.get("form")
            link = (f"{site_url}/companies/{r['cik']}" if site_url else r.get("primary_doc_url")) or ""
            lines.append(f"{name}: {what}, filed {r.get('filed_date')}\n  {link}")
        body = "New results filings for companies you follow:\n\n" + "\n\n".join(lines) + "\n\n— Disclosure"
        subject = f"Disclosure: {len(mine)} new results filing{'s' if len(mine) != 1 else ''}"
        try:
            if send(sub["email"], subject, body):
                sent += 1
        except Exception as e:
            log.error("digest to %s failed: %s", sub.get("email"), e)
    return sent


__all__ = ["is_results_filing", "load_subscriptions", "save_subscription", "send_digests", "subscription_id"]
