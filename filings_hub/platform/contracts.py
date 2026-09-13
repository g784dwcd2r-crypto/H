"""Shared identity and entitlement rules. Public availability alone is not a license.

These contracts deliberately keep publication time separate from our observation of it.
Every consumer must evaluate grants again when reading/exporting a cached artifact.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Operation = Literal["store", "display", "search", "ai", "export", "offline"]


def issuer_id(cik: int) -> str:
    if type(cik) is not int or not 0 < cik < 10**10:
        raise ValueError("CIK must be a positive integer of at most ten digits")
    return f"sec:{cik:010d}"


def sec_document_id(cik: int, accession: str, filename: str) -> str:
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ValueError("invalid SEC accession")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", filename) or ".." in filename:
        raise ValueError("invalid SEC document filename")
    return f"{issuer_id(cik)}:{accession}:{filename}"


def content_version_id(document_id: str, content: bytes) -> str:
    return "sha256:" + hashlib.sha256(document_id.encode() + b"\0" + content).hexdigest()


class DocumentRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    document_id: str
    version_id: str
    issuer_id: str
    source_id: str
    source_url: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    published_at: AwareDatetime | None = None
    discovered_at: AwareDatetime
    ingested_at: AwareDatetime
    visibility: Literal["public", "organization"] = "public"
    organization_id: str | None = None

    @model_validator(mode="after")
    def scope(self) -> DocumentRecord:
        if (self.visibility == "organization") != bool(self.organization_id):
            raise ValueError("organization documents require an organization; public documents must not have one")
        if self.ingested_at < self.discovered_at:
            raise ValueError("ingestion cannot precede discovery")
        return self


class SourceGrant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    grant_id: str
    source_id: str
    organization_id: str | None = None
    operations: frozenset[Operation] = frozenset()
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None = None
    revoked_at: AwareDatetime | None = None
    # Approval references point to the actual agreement or recorded source assessment.
    approval_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def interval(self) -> SourceGrant:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("grant end must follow start")
        return self


def permits(
    grant: SourceGrant,
    operation: Operation,
    organization_id: str | None = None,
    at: datetime | None = None,
) -> bool:
    at = at or datetime.now(UTC)
    if at.tzinfo is None:
        raise ValueError("policy evaluation requires timezone-aware time")
    return (
        operation in grant.operations
        and (grant.organization_id is None or grant.organization_id == organization_id)
        and grant.valid_from <= at
        and (grant.valid_until is None or at < grant.valid_until)
        and (grant.revoked_at is None or at < grant.revoked_at)
    )


def artifact_permitted(
    documents: list[DocumentRecord],
    grants: list[SourceGrant],
    operation: Operation,
    organization_id: str | None = None,
    at: datetime | None = None,
) -> bool:
    """All contributing sources must be entitled; an empty evidence set is not evidence of access."""
    if not documents:
        return False
    return all(
        (doc.visibility == "public" or doc.organization_id == organization_id)
        and any(grant.source_id == doc.source_id and permits(grant, operation, organization_id, at) for grant in grants)
        for doc in documents
    )
