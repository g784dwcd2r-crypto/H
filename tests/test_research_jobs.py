from time import time_ns

import pytest

from filings_hub.lake.storage import Storage
from filings_hub.research_index import ResearchIndex
from filings_hub.research_jobs import JobConflict, LeaseLost, ResearchJobs, _FencedIndex


@pytest.fixture(params=["sqlite", "postgres"])
def queue(request, tmp_path):
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    index = ResearchIndex(database_url=url, path=tmp_path / "jobs.sqlite3")
    jobs = ResearchJobs(index)
    if url:
        index.execute("DELETE FROM research_jobs")
        index.execute("UPDATE research_worker_fence SET job_id=NULL,token=NULL,expires=NULL") if index.query(
            "SELECT table_name FROM information_schema.tables WHERE table_name='research_worker_fence'"
        ) else None
    clock = [1000.0]
    jobs = ResearchJobs(index, clock=lambda: clock[0])
    jobs.test_database_url = url
    yield jobs, clock, Storage(str(tmp_path / "lake"))
    index.close()


def enqueue(jobs, **changes):
    return jobs.enqueue(kind="index", idempotency_key=f"job-{time_ns()}", **changes)


def test_durable_queue_idempotency_and_single_writer(queue):
    jobs, _, _ = queue
    first = enqueue(jobs)
    assert jobs.enqueue(kind="index", idempotency_key=first["idempotency_key"])["id"] == first["id"]
    with pytest.raises(JobConflict):
        jobs.enqueue(kind="discovery", idempotency_key=first["idempotency_key"])
    claimed = jobs.claim("worker-one")
    assert claimed["id"] == first["id"]
    assert jobs.claim("worker-two") is None
    assert ResearchJobs(jobs.index, clock=jobs.clock).get(first["id"])["status"] == "running"


def test_crash_expiration_retry_quarantine_and_restore(queue):
    jobs, clock, _ = queue
    first = enqueue(jobs)
    for _ in range(3):
        claim = jobs.claim("crashing-worker", lease_seconds=1)
        assert claim
        clock[0] += 2
        assert jobs.claim("replacement") is None
        with pytest.raises(LeaseLost):
            jobs.check(claim)
        clock[0] += 100
    row = jobs.get(first["id"])
    assert row["status"] == "quarantined"
    retry = jobs.retry(row["id"], row["revision"])
    assert retry["status"] == "queued" and retry["attempts"] == 0
    assert jobs.claim("recovered")


def test_cancel_fences_stale_writes_and_revision_conflicts(queue):
    jobs, _, _ = queue
    first = enqueue(jobs)
    claim = jobs.claim("worker")
    cancelled = jobs.cancel(first["id"], claim["revision"])
    with pytest.raises(JobConflict):
        jobs.retry(first["id"], first["revision"])
    with pytest.raises(LeaseLost):
        _FencedIndex(jobs, claim).meta("test:write", "must not happen")
    assert jobs.index.meta("test:write") is None
    assert cancelled["status"] == "cancelled"


def test_index_success_unsupported_and_budget_pause(queue):
    jobs, _, storage = queue
    from filings_hub.lake.layout import raw_document

    filing = {"cik": 88, "accession": "0000000088-26-000001", "form": "10-K", "filed_date": "2026-01-01"}
    for filename, content in [("report.txt", b"Actual cached revenue 120."), ("image.png", b"image")]:
        jobs.index.register_document(filing, {"filename": filename})
        storage.write_bytes(raw_document(88, filing["accession"], filename), content)
    enqueue(jobs, cik=88, batch_size=1, max_batches=1)
    result = jobs.run_claim(jobs.claim("worker"), None, storage)
    assert result["status"] == "paused"
    while result["status"] == "paused":
        jobs.retry(result["id"], result["revision"])
        result = jobs.run_claim(jobs.claim("worker"), None, storage)
    assert result["status"] == "completed"
    coverage = jobs.index.coverage(cik=88)
    assert coverage["indexed"] == 1 and coverage["unsupported"] == 1


def test_source_failure_retained_and_bounded(queue):
    jobs, clock, storage = queue
    jobs.index.register_document({"cik": 99, "accession": "0000000099-26-000001"}, {"filename": "missing.txt"})
    first = enqueue(jobs, cik=99)
    for _ in range(3):
        result = jobs.run_claim(jobs.claim("worker"), None, storage)
        clock[0] += 100
    assert result["id"] == first["id"] and result["status"] == "quarantined"
    assert jobs.index.coverage(cik=99)["pending"] == 1


def test_two_connections_cannot_claim_the_same_corpus(queue):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    jobs, _, _ = queue
    enqueue(jobs)
    enqueue(jobs)
    if jobs.index.postgres:
        other_index = ResearchIndex(database_url=jobs.test_database_url)
    else:
        other_index = ResearchIndex(path=jobs.index.query("PRAGMA database_list")[0]["file"])
    other = ResearchJobs(other_index, clock=jobs.clock)
    barrier = Barrier(2)

    def claim(engine):
        barrier.wait()
        return engine.claim("parallel-worker")

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, [jobs, other]))
        assert sum(result is not None for result in results) == 1
    finally:
        other_index.close()


def test_cancellation_during_source_fetch_blocks_late_storage_and_index_writes(queue):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from types import SimpleNamespace

    from filings_hub.lake.layout import raw_document

    jobs, _, storage = queue
    filing = {"cik": 66, "accession": "0000000066-26-000001"}
    doc = jobs.index.register_document(filing, {"filename": "slow.txt"})
    enqueue(jobs, cik=66, fetch=True)
    claim = jobs.claim("worker")
    started, released = Event(), Event()

    class SlowSource:
        def get(self, url):
            started.set()
            assert released.wait(3)
            return SimpleNamespace(content=b"Source data that arrives after cancellation.")

    with ThreadPoolExecutor(max_workers=1) as executor:
        task = executor.submit(jobs.run_claim, claim, None, storage, SlowSource())
        assert started.wait(3)
        jobs.cancel(claim["id"], claim["revision"])
        released.set()
        with pytest.raises(LeaseLost):
            task.result()
    assert not storage.exists(raw_document(66, filing["accession"], "slow.txt"))
    assert (
        jobs.index.query("SELECT current_version_id FROM research_documents WHERE document_id=?", [doc])[0][
            "current_version_id"
        ]
        is None
    )
