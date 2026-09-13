"""Three opt-in ownership digests, kept separate from results alerts and each other."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from filings_hub.ingest.digest import DigestDeliveryError, load_subscriptions, subscription_id

FLOW_LABELS = {
    "insiders": "insider filings",
    "institutions": "institutional reported holdings",
    "events": "major ownership disclosures",
}


def send_ownership_digests(store, storage, *, sender=None, site_url: str = "", max_pages: int = 20) -> int:
    """Replay safe after failures, with one receipt per source event per subscriber and flow.

    Queries are paged by immutable filing events, never collapsed latest-person cards. The first
    undelivered page is sent each run. A rotating scan cursor eventually revisits delayed sources.
    As with results alerts, SMTP success followed by a receipt-write crash can duplicate a message.
    """
    from filings_hub.ingest import alerts

    send = sender or alerts.send_email
    sent = failures = 0
    for sub in load_subscriptions(storage):
        ciks = [int(c) for c in sub.get("ciks", [])]
        if not ciks:
            continue
        for kind, label in FLOW_LABELS.items():
            if kind not in sub.get("ownership_flows", []):
                continue
            since = (sub.get("ownership_started") or {}).get(kind) or sub.get("created")
            if not since:
                continue  # Legacy records never implicitly subscribe to historical ownership.
            since = str(since)[:10]
            sid = subscription_id(sub["email"])
            prefix = f"ownership/deliveries/{sid}/{kind}"
            mine = []
            audience = hashlib.sha256(json.dumps([sorted(ciks), since]).encode()).hexdigest()[:16]
            cursor_key = f"notify:{sid}:{kind}:{audience}"
            offset = int((store.get_state(cursor_key) or {}).get("offset", 0))
            next_offset = offset
            # Cycle back to zero at the end, so late filings and newly mapped positions are revisited.
            for _ in range(max_pages):
                events = store.notification_events(ciks, since, kind, limit=100, offset=offset)
                next_offset = 0 if len(events) < 100 else offset + len(events)
                for event in events:
                    rid = hashlib.sha256(str(event["id"]).encode()).hexdigest()
                    if not storage.exists(f"{prefix}/{rid}.json"):
                        mine.append((rid, event))
                if mine or len(events) < 100:
                    break
                offset = next_offset
            if not mine:
                store.set_state(cursor_key, {"offset": next_offset})
                continue
            lines = []
            for _, event in mine:
                link = (
                    f"{site_url.rstrip('/')}/companies/{event['cik']}/ownership#{kind}"
                    if site_url
                    else event.get("source_url", "")
                )
                lines.append(
                    f"{event.get('name') or 'CIK ' + str(event['cik'])}: {event.get('summary') or event['form']}\n"
                    f"Filed {event['filed_date']} · {event['form']}\n{link}"
                )
            body = (
                f"New {label} for companies you follow:\n\n"
                + "\n\n".join(lines)
                + "\n\nThese are reported observations with filing lags and incomplete coverage, "
                "not a complete owner register." + "\nManage these alerts in your Disclosure watchlist.\n\n— Disclosure"
            )
            try:
                if not send(sub["email"], f"Disclosure: {len(mine)} new {label}", body):
                    failures += 1
                    continue
                for rid, event in mine:
                    record = json.dumps({"event_id": event["id"], "sent_at": datetime.now(UTC).isoformat()})
                    rel = f"{prefix}/{rid}.json"
                    if storage.is_remote:
                        storage.write_text(rel, record)
                    else:
                        storage.write_text(rel + ".tmp", record)
                        storage.fs.mv(storage.full(rel + ".tmp"), storage.full(rel))
                store.set_state(cursor_key, {"offset": next_offset})
                sent += 1
            except Exception:
                failures += 1
    if failures:
        raise DigestDeliveryError(sent, failures)
    return sent
