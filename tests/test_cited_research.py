from datetime import UTC, date, datetime
from time import time_ns

import pytest

from filings_hub import accounts
from filings_hub.lake.storage import Storage
from filings_hub.research_corpus import ResearchCorpus
from filings_hub.research_index import open_index
from filings_hub.research_questions import Question, ResearchQuestions
from filings_hub.tenancy import SecurityError, SecurityStore
from filings_hub.testing.research_provider import FixtureResearchProvider


@pytest.fixture(params=["sqlite", "postgres"])
def research(request, tmp_path):
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    storage = Storage(str(tmp_path))
    users = accounts.store_from_settings(storage, url)
    security = SecurityStore(users, storage, url)
    owner = users.create_user(f"research-{time_ns()}@example.test")
    index = open_index(storage, url)
    original_documents = {row["document_id"] for row in index.query("SELECT document_id FROM research_documents")}
    corpus = ResearchCorpus(index)
    provider = FixtureResearchProvider()
    service = ResearchQuestions(corpus, security, provider)
    versions = []
    for cik, text in [
        (1, "Revenue was 1,200 and previous revenue was 1,000. Liquidity is adequate."),
        (2, "Contradictory evidence: liquidity may be insufficient during severe stress."),
    ]:
        filing = {"cik": cik, "accession": f"{cik:010d}-26-000001", "form": "10-K", "filed_date": "2026-01-01"}
        doc = index.register_document(filing, {"filename": f"source-{time_ns()}.txt"})
        versions.append(index.add_version(storage, doc, text.encode(), text))
    corpus.prepare(limit=100)
    # A shared PG test cluster may contain other eligible test versions; embed all bounded batches.
    while corpus.embed_batch(provider)["embedded_spans"]:
        pass
    provider.calls.clear()
    yield service, owner.id, versions, users, index
    if url:
        # This suite shares one temporary database with lexical parity tests. Retain only
        # pre-existing fixtures, including any other test's immutable source registry.
        for row in index.query("SELECT document_id FROM research_documents"):
            if row["document_id"] in original_documents:
                continue
            for version in index.query(
                "SELECT version_id FROM research_versions WHERE document_id=?", [row["document_id"]]
            ):
                ident = version["version_id"]
                for table in ("research_embeddings", "research_span_terms", "research_span_projections"):
                    index.execute(
                        f"DELETE FROM {table} WHERE span_id IN (SELECT span_id FROM research_spans WHERE version_id=?)",
                        [ident],
                    )
                for table in (
                    "research_spans",
                    "research_prepared_projection",
                    "research_prepared_versions",
                    "research_preparation_failures",
                    "research_text_projections",
                    "research_terms",
                ):
                    index.execute(f"DELETE FROM {table} WHERE version_id=?", [ident])
                index.execute("DELETE FROM research_versions WHERE version_id=?", [ident])
            index.execute("DELETE FROM research_documents WHERE document_id=?", [row["document_id"]])
    index.close()
    if url:
        users.conn.close()


def question(versions, **changes):
    return Question(
        question="What does the source say about liquidity and revenue?",
        version_ids=versions,
        as_of=datetime.now(UTC).date(),
        idempotency_key=f"request-{time_ns()}",
        **changes,
    )


def test_hybrid_answer_exact_spans_conflicts_and_idempotency(research):
    service, actor, versions, _, _ = research
    request = question(versions)
    run = service.create(request, actor)
    assert run["status"] == "conflicting_evidence"
    assert run["provider"]["fixture"]
    assert run["usage"]["provider_calls"] == 3
    assert len(run["passages"]) == 2
    for claim in run["claims"]:
        assert claim["assessment"] == "machine_assessed"
        for evidence in claim["evidence"]:
            passage = service.corpus.span(evidence["span_id"])
            assert evidence["quote"] in passage["text"]
    assert service.create(request, actor)["id"] == run["id"]
    assert len(service.provider.calls) == 3
    request.question = "A different question"
    with pytest.raises(SecurityError, match="different question"):
        service.create(request, actor)


def test_future_capture_and_selected_scope_do_not_leak(research):
    service, actor, versions, _, index = research
    index.execute(
        "UPDATE research_versions SET indexed_at=? WHERE version_id=?", ["2099-01-01T00:00:00+00:00", versions[1]]
    )
    run = service.create(question(versions), actor)
    assert len(run["passages"]) == 1 and run["coverage"]["excluded_after_cutoff"] == 1
    assert run["passages"][0]["version_id"] == versions[0]
    old = question(versions)
    old.as_of = date(2025, 1, 1)
    empty = service.create(old, actor)
    assert empty["status"] == "insufficient_evidence" and empty["passages"] == []
    assert empty["usage"]["provider_calls"] == 0


def test_missing_embeddings_and_unsupported_answers_are_explicit(research):
    service, actor, versions, _, _ = research
    service.provider.embedding_model = "not-prepared"
    run = service.create(question(versions), actor)
    assert run["status"] == "failed" and run["usage"]["provider_calls"] == 0
    assert "embeddings" in run["limitations"][-1]
    service.provider.embedding_model = "synthetic-embedding-fixture"
    request = question(versions)
    request.question = "unsupported question about a future acquisition"
    assert service.create(request, actor)["status"] == "insufficient_evidence"
    service.provider.bad_quote = True
    assert service.create(question(versions), actor)["claims"] == []


def test_support_review_rejects_unfounded_claims(research):
    service, actor, versions, _, _ = research
    service.provider.reject = True
    run = service.create(question(versions), actor)
    assert run["status"] == "insufficient_evidence" and not run["claims"]
    assert any("withheld" in item for item in run["limitations"])


def test_account_project_and_source_revocation_withhold_derived_text(research):
    service, actor, versions, users, index = research
    other = users.create_user(f"other-{time_ns()}@example.test").id
    run = service.create(question(versions), actor)
    with pytest.raises(SecurityError):
        service.get(run["id"], other)
    org = service.security.create_organization(other, "Validation team")["id"]
    service.security.change_member(org, other, actor, "member")
    project = service.projects.create(actor, {"name": "Evidence review", "organization_id": org})
    saved = service.save(run["id"], actor, project["id"])
    assert saved["project_id"] == project["id"]
    assert service.get(run["id"], other)["claims"]
    service.security.change_member(org, other, actor, action="remove")
    with pytest.raises(SecurityError):
        service.get(run["id"], actor)
    index.execute("UPDATE research_documents SET visibility='organization' WHERE current_version_id=?", [versions[0]])
    with pytest.raises(SecurityError):
        service.get(run["id"], other)
    assert service.list_project(project["id"], other) == []


def test_captured_private_version_never_enters_semantics(research):
    service, actor, versions, _, index = research
    import json

    row = index.query("SELECT source_metadata FROM research_versions WHERE version_id=?", [versions[0]])[0]
    metadata = {**json.loads(row["source_metadata"]), "visibility": "organization"}
    index.execute(
        "UPDATE research_versions SET source_metadata=? WHERE version_id=?", [json.dumps(metadata), versions[0]]
    )
    run = service.create(question(versions), actor)
    assert run["status"] == "failed" and run["passages"] == []
    assert not service.provider.calls


def test_exact_decimal_calculation_and_immutable_project_artifact(research):
    service, actor, versions, _, _ = research
    run = service.create(question(versions[:1]), actor)
    passage = run["passages"][0]
    operands = [
        {
            "span_id": passage["span_id"],
            "start": passage["text"].index(text),
            "end": passage["text"].index(text) + len(text),
            "unit": "USD millions",
        }
        for text in ("1,200", "1,000")
    ]
    payload = {"operation": "growth", "operands": operands, "idempotency_key": "growth-00001"}
    updated = service.calculate(run["id"], actor, payload)
    assert updated["calculations"][0]["value"] == "20.0"
    assert len(service.calculate(run["id"], actor, payload)["calculations"]) == 1
    payload["operands"][1]["unit"] = "EUR millions"
    payload["idempotency_key"] = "growth-00002"
    with pytest.raises(SecurityError, match="units must match"):
        service.calculate(run["id"], actor, payload)
    project = service.projects.create(actor, {"name": "Model sources"})
    service.save(run["id"], actor, project["id"])
    with pytest.raises(SecurityError, match="unsaved"):
        service.calculate(run["id"], actor, payload)


def test_followup_scope_cannot_silently_change(research):
    service, actor, versions, _, _ = research
    run = service.create(question(versions), actor)
    follow = question(versions[:1], parent_run_id=run["id"])
    with pytest.raises(SecurityError, match="retain"):
        service.create(follow, actor)
    follow = question(versions, parent_run_id=run["id"])
    assert service.create(follow, actor)["parent_run_id"] == run["id"]
    context = [payload for name, payload in service.provider.calls if name == "cited_research"][-1]
    assert context["previous_question"] == run["question"]
    assert context["previous_claims_for_context_only"][0]["text"] == run["claims"][0]["text"]
    assert "evidence" not in context["previous_claims_for_context_only"][0]


def test_updated_projection_keeps_original_capture_and_old_offsets(research):
    service, _actor, _, _, index = research
    storage = index.storage
    raw = b'<html><head><title>Metadata</title></head><body><ix:header><ix:hidden>PRIVATE XBRL 999999</ix:hidden></ix:header><div style="display:none">HIDDEN 888888</div><p>Revenue 1,200. Previous revenue 1,000.</p></body></html>'
    doc = index.register_document(
        {"cik": 55, "accession": "0000000055-26-000001", "filed_date": "2026-01-01"},
        {"filename": f"old-{time_ns()}.htm"},
    )
    version = index.add_version(storage, doc, raw, "Old preserved text. HIDDEN 888888 Revenue 1,200.")
    index.execute("UPDATE research_versions SET extractor_version='disclosure-text-v1' WHERE version_id=?", [version])
    index.execute("INSERT INTO research_spans VALUES(?,?,?,?,?)", ["span:old-" + str(time_ns()), version, 0, 3, "Old"])
    original = index.version(version)["text_content"]
    service.corpus.prepare(limit=100)
    projected = index.query("SELECT projection_id FROM research_prepared_projection WHERE version_id=?", [version])[0][
        "projection_id"
    ]
    text = service.corpus.projection(projected)["text_content"]
    assert text == "Revenue 1,200. Previous revenue 1,000."
    assert index.version(version)["text_content"] == original
    old = index.query("SELECT span_id FROM research_spans WHERE version_id=? AND text_content=?", [version, "Old"])[0][
        "span_id"
    ]
    assert service.corpus.span(old)["text"] == "Old"
    assert service.corpus.projection(projected)["version_id"] == version
    index.execute("UPDATE research_documents SET visibility='organization' WHERE document_id=?", [doc])
    assert service.corpus.projection(projected) is None and service.corpus.span(old) is None


def test_source_revoked_after_draft_prevents_next_provider_call(research):
    service, actor, versions, _, index = research
    original = service.provider.structured

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        index.execute(
            "UPDATE research_documents SET visibility='organization' WHERE current_version_id=?", [versions[0]]
        )
        return result

    service.provider.structured = revoke
    run = service.create(question(versions[:1]), actor)
    assert run["status"] == "failed" and run["passages"] == []
    assert len(service.provider.calls) == 2  # query embedding + draft; no later source transmission


def test_preparation_failures_are_durable_skip_starvation_and_retry(research):
    service, _actor, _, _, index = research
    version_ids = []
    for number in range(2):
        text = f"Independent visible body {number}"
        doc = index.register_document(
            {"cik": 12, "accession": "0000000012-26-000001", "form": "10-K", "filed_date": "2026-01-01"},
            {"filename": f"prepare-failure-{number}-{time_ns()}.txt"},
        )
        version_ids.append(index.add_version(index.storage, doc, text.encode(), text))
    first = version_ids[0]
    index.execute(
        "UPDATE research_versions SET extractor_version='disclosure-text-v1',indexed_at=? WHERE version_id=?",
        ["2000-01-01T00:00:00+00:00", first],
    )
    path = index.query("SELECT raw_path FROM research_versions WHERE version_id=?", [first])[0]["raw_path"]
    with index.storage.open(path) as stream:
        original = stream.read()
    index.storage.write_bytes(path, b"corrupted bytes")
    before = service.corpus.health()["preparation_failed"]
    result = service.corpus.prepare(limit=1)
    assert result["prepared_versions"] == 0 and result["preparation_failed"] == before + 1
    reopened = ResearchCorpus(index)
    assert reopened.prepare(limit=1)["prepared_versions"] == 1
    assert reopened.prepare(limit=1)["prepared_versions"] == 0
    assert (
        index.query("SELECT error_code FROM research_preparation_failures WHERE version_id=?", [first])[0]["error_code"]
        == "hash_mismatch"
    )
    index.storage.write_bytes(path, original)
    assert reopened.prepare(limit=1, retry_failed=True)["prepared_versions"] == 1
    assert not index.query("SELECT * FROM research_preparation_failures WHERE version_id=?", [first])


def test_lexical_reranking_is_bounded_and_has_no_embedding_request(research):
    service, actor, versions, _, _ = research
    service.provider.retrieval_mode = "lexical_rerank"
    service.provider.embedding_model = ""
    service.provider.rerank_candidate_limit = 3
    service.provider.retrieved_passage_limit = 2
    run = service.create(question(versions), actor)
    assert run["status"] == "conflicting_evidence"
    assert run["coverage"]["retrieval_mode"] == "lexical_rerank"
    assert run["coverage"]["rerank_candidates"] == 2
    assert [call[0] for call in service.provider.calls] == [
        "research_relevance",
        "cited_research",
        "research_support_review",
    ]


def test_capability_requires_prepared_current_model_and_blank_questions_fail(research):
    service, _actor, versions, _, _index = research
    assert service.capabilities()["available"]
    service.provider.embedding_model = "unprepared-new-model"
    assert service.capabilities()["unavailable_reason"] == "corpus_not_prepared"
    assert not service.capabilities()["available"]
    service.provider.retrieval_mode = "lexical_rerank"
    assert service.capabilities()["available"]
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="non-padding"):
        Question(question="   ", version_ids=versions, as_of=date.today(), idempotency_key="blank-request")


def test_calculations_preserve_unicode_minus_and_reject_unsigned_suffixes():
    from filings_hub.research_questions import calculate

    text = "Cash change −1,200. Positive 1,000. Ambiguous –1,200 and − 1,200 and ( 1,200 )."
    passage = {"span_id": "source-span", "start": 0, "end": len(text), "text": text}

    def operand(literal, offset=0):
        start = text.index(literal, offset)
        return {"span_id": "source-span", "start": start, "end": start + len(literal), "unit": "USD millions"}

    positive = operand("1,000")
    result = calculate(
        {"operation": "sum", "operands": [operand("−1,200"), positive], "idempotency_key": "negative-1"}, [passage]
    )
    assert result["value"] == "-200"
    assert result["operands"][0]["text"] == "−1,200"
    for start in [
        text.index("−1,200") + 1,
        text.index("–1,200") + 1,
        text.index("− 1,200") + 2,
        text.index("( 1,200") + 2,
    ]:
        partial = {"span_id": "source-span", "start": start, "end": start + 5, "unit": "USD millions"}
        with pytest.raises(SecurityError, match="complete numeric"):
            calculate({"operation": "sum", "operands": [partial, positive], "idempotency_key": "negative-2"}, [passage])
