from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from filings_hub.platform.contracts import (
    DocumentRecord,
    SourceGrant,
    artifact_permitted,
    content_version_id,
    permits,
    sec_document_id,
)

NOW = datetime(2026, 9, 13, tzinfo=UTC)


def test_document_and_content_identity():
    apple = sec_document_id(320193, "0000320193-24-000123", "aapl-20240928.htm")
    assert apple.startswith("sec:0000320193:")
    assert content_version_id(apple, b"v1") != content_version_id(apple, b"v2")
    assert content_version_id(apple, b"v1") != content_version_id(apple + "x", b"v1")
    with pytest.raises(ValueError):
        sec_document_id(320193, "0000320193-24-000123", "../secret")


def test_grants_are_explicit_operation_scoped_and_revocable():
    grant = SourceGrant(
        grant_id="g1",
        source_id="licensed",
        organization_id="org-a",
        operations={"search", "display"},
        valid_from=NOW,
        valid_until=NOW + timedelta(days=1),
        approval_reference="agreement/1",
    )
    assert permits(grant, "search", "org-a", NOW)
    assert not permits(grant, "ai", "org-a", NOW)
    assert not permits(grant, "search", "org-b", NOW)
    assert not permits(grant, "search", "org-a", NOW + timedelta(days=1))
    assert not permits(grant.model_copy(update={"revoked_at": NOW}), "search", "org-a", NOW)
    with pytest.raises(ValueError):
        permits(grant, "search", "org-a", datetime(2026, 9, 13))


def test_mixed_source_artifact_checks_every_grant_at_read_time():
    doc = DocumentRecord(
        document_id="a",
        version_id="v1",
        issuer_id="issuer-a",
        source_id="source-a",
        source_url="https://example.com/a",
        content_sha256="a" * 64,
        discovered_at=NOW,
        ingested_at=NOW,
    )
    grant = SourceGrant(
        grant_id="a", source_id="source-a", operations={"export"}, valid_from=NOW, approval_reference="assessment/a"
    )
    assert artifact_permitted([doc], [grant], "export", at=NOW)
    assert not artifact_permitted([doc, doc.model_copy(update={"source_id": "source-b"})], [grant], "export", at=NOW)
    assert not artifact_permitted([], [grant], "export", at=NOW)
    private = doc.model_copy(update={"visibility": "organization", "organization_id": "org-a"})
    assert not artifact_permitted([private], [grant], "export", "org-b", NOW)
    with pytest.raises(ValidationError):
        DocumentRecord(**{**doc.model_dump(), "visibility": "organization"})
