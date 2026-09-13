import json

import pytest

from filings_hub.ingest.digest import DigestDeliveryError, save_subscription, subscription_id
from filings_hub.lake.storage import Storage
from filings_hub.ownership.digest import send_ownership_digests


class Events:
    def __init__(self, size=1):
        self.size, self.state = size, {}

    def get_state(self, key):
        return self.state.get(key)

    def set_state(self, key, value):
        self.state[key] = value

    def notification_events(self, ciks, since, kind, limit=100, offset=0):
        assert ciks == [320193] and since == "2026-09-10"
        return [
            {
                "id": f"{kind}-{n}",
                "cik": 320193,
                "form": "4" if kind == "insiders" else "13F-HR" if kind == "institutions" else "SCHEDULE 13D",
                "filed_date": since,
                "name": "Synthetic company",
                "summary": "Synthetic reported observation",
                "source_url": "https://www.sec.gov/Archives/edgar/data/320193/fixture.xml",
            }
            for n in range(offset, min(offset + limit, self.size))
        ]


def subscribe(storage, flows):
    record = save_subscription(storage, "analyst@example.test", [320193])
    record.update(created="2026-09-10", ownership_flows=flows)
    storage.write_text(f"subscriptions/{subscription_id(record['email'])}.json", json.dumps(record))


def test_opt_in_flows_send_separate_messages_and_receipts_prevent_replay(tmp_path):
    storage, events, sent = Storage(str(tmp_path)), Events(), []
    subscribe(storage, [])
    assert send_ownership_digests(events, storage, sender=lambda *args: sent.append(args) or True) == 0
    subscribe(storage, ["insiders", "institutions", "events"])
    assert send_ownership_digests(events, storage, sender=lambda *args: sent.append(args) or True) == 3
    assert len({mail[1] for mail in sent}) == 3
    assert send_ownership_digests(events, storage, sender=lambda *args: sent.append(args) or True) == 0
    assert len(sent) == 3


def test_failed_delivery_retries_and_bounded_scan_rotates_to_late_events(tmp_path):
    storage, events, sent = Storage(str(tmp_path)), Events(205), []
    subscribe(storage, ["insiders"])
    with pytest.raises(DigestDeliveryError):
        send_ownership_digests(events, storage, sender=lambda *_: False, max_pages=1)
    for _ in range(3):
        assert send_ownership_digests(events, storage, sender=lambda *args: sent.append(args) or True, max_pages=1) == 1
    assert len(storage.glob("ownership/deliveries/*/insiders/*.json")) == 205
    # Two already-receipted pages are scanned in two bounded invocations. A new last-page source is eventually delivered.
    events.size = 206
    assert send_ownership_digests(events, storage, sender=lambda *args: sent.append(args) or True, max_pages=1) == 0
    assert send_ownership_digests(events, storage, sender=lambda *args: sent.append(args) or True, max_pages=1) == 0
    assert send_ownership_digests(events, storage, sender=lambda *args: sent.append(args) or True, max_pages=1) == 1
    assert len(storage.glob("ownership/deliveries/*/insiders/*.json")) == 206
