from datetime import date

import pytest

from filings_hub.ingest import digest
from filings_hub.lake.storage import Storage


def filing(accession, cik=320193):
    return {"accession": accession, "cik": cik, "form": "10-K", "filed_date": date(2026, 11, 2)}


def test_digest_replays_skip_delivered_accessions_across_batches(tmp_path):
    storage = Storage(str(tmp_path))
    digest.save_subscription(storage, "analyst@example.com", [320193])
    messages = []

    def sender(*args):
        messages.append(args)
        return True

    assert digest.send_digests(storage, [filing("one")], {}, sender=sender) == 1
    assert digest.send_digests(storage, [filing("one")], {}, sender=sender) == 0
    assert digest.send_digests(storage, [filing("one"), filing("two"), filing("two")], {}, sender=sender) == 1
    assert len(messages) == 2 and "1 new results filing" in messages[-1][1]


@pytest.mark.parametrize("raises", [False, True])
def test_digest_retry_only_failed_subscribers(tmp_path, raises):
    storage = Storage(str(tmp_path))
    for email in ("success@example.com", "failure@example.com"):
        digest.save_subscription(storage, email, [320193])

    def sender(email, *args):
        if email.startswith("failure"):
            if raises:
                raise RuntimeError("SMTP unavailable")
            return False
        return True

    with pytest.raises(digest.DigestDeliveryError) as error:
        digest.send_digests(storage, [filing("one")], {}, sender=sender)
    assert error.value.sent == 1
    retried = []
    assert (
        digest.send_digests(storage, [filing("one")], {}, sender=lambda email, *args: retried.append(email) or True)
        == 1
    )
    assert retried == ["failure@example.com"]
