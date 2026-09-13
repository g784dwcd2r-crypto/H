"""Durable bounded SEC indexing jobs, explicit workers, and fenced write authority.

One global writer lease deliberately trades throughput for correctness. This worker does not start
when the API starts. Operators enqueue jobs and run bounded worker invocations against isolated or
approved storage. Unsupported source inventories remain registered throughout retries/cancellation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from filings_hub.research_corpus import _initialize
from filings_hub.research_index import now
from filings_hub.research_ingest import discover_batch, index_documents_batch


class JobConflict(ValueError):
    pass


class LeaseLost(RuntimeError):
    pass


class ResearchJobs:
    def __init__(self, index, *, clock=time.time):
        self.index, self.clock = index, clock
        _initialize(index, (Path(__file__).parent / "db/migrations/0013_research_jobs.sql").read_text())

    @contextmanager
    def transaction(self):
        with self.index.transaction():
            if self.index.postgres:
                self.index.query("SELECT id FROM research_worker_fence WHERE id=1 FOR UPDATE")
            yield

    def _put(self, job):
        job["updated_at"] = now()
        self.index.execute(
            "INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "status=excluded.status,revision=excluded.revision,not_before=excluded.not_before,"
            "lease_expires=excluded.lease_expires,record=excluded.record",
            [
                job["id"],
                job["idempotency_key"],
                job["status"],
                job["revision"],
                job["not_before"],
                job["lease_expires_at"],
                json.dumps(job),
            ],
        )

    def get(self, ident):
        rows = self.index.query("SELECT record FROM research_jobs WHERE id=?", [ident])
        return json.loads(rows[0]["record"]) if rows else None

    def list(self, *, limit=50, offset=0):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Job page limit must be 1–100 and offset nonnegative.")
        total = self.index.query("SELECT count(*) n FROM research_jobs")[0]["n"]
        rows = self.index.query("SELECT record FROM research_jobs ORDER BY id LIMIT ? OFFSET ?", [limit, offset])
        return {"jobs": [json.loads(row["record"]) for row in rows], "total": total}

    def enqueue(self, *, kind, cik=None, idempotency_key, fetch=False, max_batches=20, batch_size=10):
        if kind not in ("discovery", "index") or (cik is not None and not 0 < cik < 10**10):
            raise ValueError("Select discovery or index and a valid optional CIK.")
        if not 1 <= max_batches <= 100 or not 1 <= batch_size <= 25:
            raise ValueError("Jobs permit 1–100 batches of 1–25 items.")
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 100:
            raise ValueError("Idempotency key must contain 8–100 characters.")
        spec = dict(kind=kind, cik=cik, fetch=bool(fetch), max_batches=max_batches, batch_size=batch_size)
        digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        with self.transaction():
            old = self.index.query("SELECT record FROM research_jobs WHERE idempotency_key=?", [idempotency_key])
            if old:
                job = json.loads(old[0]["record"])
                if job["request_hash"] != digest:
                    raise JobConflict("Idempotency key already identifies a different job.")
                return job
            job = {
                "id": uuid.uuid4().hex,
                **spec,
                "idempotency_key": idempotency_key,
                "request_hash": digest,
                "status": "queued",
                "revision": 1,
                "created_at": now(),
                "updated_at": now(),
                "attempts": 0,
                "max_attempts": 3,
                "batches_completed": 0,
                "lease_expires_at": None,
                "not_before": self.clock(),
                "error": None,
                "progress": {},
                "token": None,
                "worker_id": None,
            }
            self._put(job)
            return job

    def _change(self, ident, expected_revision, action):
        with self.transaction():
            job = self.get(ident)
            if job is None or job["revision"] != expected_revision:
                raise JobConflict("Job was missing or changed; refresh before acting.")
            if action == "cancel":
                if job["status"] in ("completed", "cancelled"):
                    return job
                job.update(status="cancelled", token=None, lease_expires_at=None)
            else:
                if job["status"] not in ("paused", "quarantined", "retry_wait", "cancelled"):
                    raise JobConflict("Only paused, quarantined, waiting or cancelled jobs can be retried.")
                job.update(
                    status="queued",
                    attempts=0,
                    batches_completed=0,
                    token=None,
                    lease_expires_at=None,
                    not_before=self.clock(),
                    error=None,
                )
            job["revision"] += 1
            self._put(job)
            self.index.execute(
                "UPDATE research_worker_fence SET job_id=NULL,token=NULL,expires=NULL WHERE job_id=?", [ident]
            )
            return job

    def cancel(self, ident, expected_revision):
        return self._change(ident, expected_revision, "cancel")

    def retry(self, ident, expected_revision):
        return self._change(ident, expected_revision, "retry")

    def claim(self, worker_id, *, lease_seconds=300):
        if not 1 <= lease_seconds <= 3600 or not isinstance(worker_id, str) or not 1 <= len(worker_id) <= 100:
            raise ValueError("Invalid worker lease.")
        with self.transaction():
            timestamp = self.clock()
            fence = self.index.query("SELECT * FROM research_worker_fence WHERE id=1")[0]
            if fence["expires"] and fence["expires"] > timestamp:
                return None
            expired = self.index.query(
                "SELECT record FROM research_jobs WHERE status='running' AND lease_expires<=?", [timestamp]
            )
            for row in expired:
                job = json.loads(row["record"])
                job.update(
                    status="quarantined" if job["attempts"] >= job["max_attempts"] else "retry_wait",
                    error="Worker lease expired; bounded batch may have partially completed.",
                    token=None,
                    lease_expires_at=None,
                    not_before=timestamp + min(300, 2 ** job["attempts"] * 5),
                )
                job["revision"] += 1
                self._put(job)
            rows = self.index.query(
                "SELECT record FROM research_jobs WHERE status IN ('queued','retry_wait') "
                "AND not_before<=? ORDER BY not_before,id LIMIT 1",
                [timestamp],
            )
            if not rows:
                return None
            job = json.loads(rows[0]["record"])
            token = uuid.uuid4().hex
            job.update(status="running", worker_id=worker_id, token=token, lease_expires_at=timestamp + lease_seconds)
            job["attempts"] += 1
            job["revision"] += 1
            self._put(job)
            self.index.execute(
                "UPDATE research_worker_fence SET job_id=?,token=?,expires=? WHERE id=1",
                [job["id"], token, job["lease_expires_at"]],
            )
            return job

    def check(self, job):
        fence = self.index.query("SELECT * FROM research_worker_fence WHERE id=1")[0]
        if fence["job_id"] != job["id"] or fence["token"] != job["token"] or fence["expires"] <= self.clock():
            raise LeaseLost("Worker authority expired or was cancelled; no further corpus writes are permitted.")

    def heartbeat(self, job, *, lease_seconds=300):
        with self.transaction():
            self.check(job)
            current = self.get(job["id"])
            current["lease_expires_at"] = self.clock() + lease_seconds
            self._put(current)
            self.index.execute("UPDATE research_worker_fence SET expires=? WHERE id=1", [current["lease_expires_at"]])
            return current

    def run_claim(self, job, database, storage, client=None):
        if job["fetch"] and client is None:
            return self._finish(job, None, "Source fetching was requested but no configured SEC client was supplied.")
        guarded = _FencedIndex(self, job)
        guarded_storage = _FencedStorage(self, job, storage)
        try:
            self.check(job)
            if job["kind"] == "discovery":
                cursor_key = f"discovery:{job['cik'] if job['cik'] is not None else 'all'}:cursor"
                previous_cursor = guarded.meta(cursor_key) or {}
                progress = discover_batch(
                    database,
                    guarded_storage,
                    guarded,
                    limit=job["batch_size"],
                    cik=job["cik"],
                    client=client if job["fetch"] else None,
                )
                done = progress["discovery_complete"]
                if progress["inventories"]["failed"] or progress["inventories"]["pending"]:
                    guarded.meta(cursor_key, previous_cursor)
                    return self._finish(
                        job, progress, "Filing inventories are incomplete; registered documents remain visible."
                    )
            else:
                progress = index_documents_batch(
                    guarded_storage,
                    guarded,
                    limit=job["batch_size"],
                    cik=job["cik"],
                    client=client if job["fetch"] else None,
                    retry_failed=True,
                    retry_unsupported=False,
                )
                done = progress["attempted"] == 0
                if progress["failed"] or progress["pending"]:
                    return self._finish(
                        job, progress, "Some source documents failed or remain uncached; inspect inventory."
                    )
            return self._finish(job, progress, None, done=done)
        except LeaseLost:
            raise
        except Exception as exc:
            return self._finish(job, None, f"Bounded indexing batch failed ({type(exc).__name__}).")

    def _finish(self, job, progress, error, *, done=False):
        with self.transaction():
            self.check(job)
            current = self.get(job["id"])
            current["batches_completed"] += 1
            current["progress"] = progress or {}
            if error:
                state = "quarantined" if current["attempts"] >= current["max_attempts"] else "retry_wait"
            elif done:
                state = "completed"
            elif current["batches_completed"] >= current["max_batches"]:
                state = "paused"
            else:
                state = "queued"
                current["attempts"] = 0
            current.update(
                status=state,
                error=error,
                token=None,
                lease_expires_at=None,
                not_before=self.clock() + (min(300, 2 ** current["attempts"] * 5) if error else 0),
            )
            current["revision"] += 1
            self._put(current)
            self.index.execute("UPDATE research_worker_fence SET job_id=NULL,token=NULL,expires=NULL WHERE id=1")
            return current

    def health(self):
        jobs = {
            r["status"]: r["n"] for r in self.index.query("SELECT status,count(*) n FROM research_jobs GROUP BY status")
        }
        rows = self.index.query("SELECT record FROM research_jobs WHERE status IN ('queued','completed')")
        records = [json.loads(row["record"]) for row in rows]
        return {
            "jobs": jobs,
            "oldest_queued_at": min((r["created_at"] for r in records if r["status"] == "queued"), default=None),
            "last_completed_at": max((r["updated_at"] for r in records if r["status"] == "completed"), default=None),
            "coverage": self.index.coverage(),
            "scheduler_active": False,
        }


class _FencedIndex:
    def __init__(self, jobs, job):
        self.jobs, self.job = jobs, job

    def __getattr__(self, key):
        target = getattr(self.jobs.index, key)
        if key in ("register_filing", "register_document", "inventory_status", "document_status", "add_version"):

            def fenced(*args, **kwargs):
                # Hold the global fence lock throughout the atomic mutation; cancellation cannot pass it.
                with self.jobs.transaction():
                    self.jobs.check(self.job)
                    # add_version owns its own transaction, so it uses the shared transaction via savepoint.
                    return target(*args, **kwargs)

            return fenced
        return target

    def meta(self, key, value=None):
        if key.endswith(":cursor"):
            key = "job:" + self.job["id"] + ":" + key
        if value is None:
            return self.jobs.index.meta(key)
        with self.jobs.transaction():
            self.jobs.check(self.job)
            return self.jobs.index.meta(key, value)


class _FencedStorage:
    def __init__(self, jobs, job, storage):
        self.jobs, self.job, self.storage = jobs, job, storage

    def __getattr__(self, key):
        target = getattr(self.storage, key)
        if key in ("write_bytes", "write_text"):

            def fenced(*args, **kwargs):
                with self.jobs.transaction():
                    self.jobs.check(self.job)
                    return target(*args, **kwargs)

            return fenced
        return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("enqueue", "work", "status", "retry", "cancel", "prepare", "embed"))
    parser.add_argument("--kind", choices=("discovery", "index"), default="discovery")
    parser.add_argument("--cik", type=int)
    parser.add_argument("--idempotency-key")
    parser.add_argument("--job")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--retry-preparation-failures", action="store_true")
    parser.add_argument("--max-batches", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()
    from filings_hub.config import get_settings
    from filings_hub.db.database import Database
    from filings_hub.ingest.edgar_client import EdgarClient
    from filings_hub.lake.storage import Storage
    from filings_hub.research_corpus import ResearchCorpus
    from filings_hub.research_index import open_index
    from filings_hub.research_provider import provider_from_settings

    settings = get_settings()
    storage = Storage(settings.resolved_lake_root())
    index = open_index(storage, settings.database_url)
    jobs = ResearchJobs(index)
    client = database = None
    try:
        if args.action == "enqueue":
            result = jobs.enqueue(
                kind=args.kind,
                cik=args.cik,
                idempotency_key=args.idempotency_key,
                fetch=args.fetch,
                max_batches=args.max_batches,
                batch_size=args.batch_size,
            )
        elif args.action == "work":
            job = jobs.claim("cli:" + uuid.uuid4().hex)
            if job:
                database = Database(settings.database_url, storage)
                client = (
                    EdgarClient(
                        settings.sec_user_agent, requests_per_second=2, max_retries=1, throttle_retries=0, timeout=8
                    )
                    if job["fetch"]
                    else None
                )
                result = jobs.run_claim(job, database, storage, client)
            else:
                result = {"status": "idle", "explanation": "No eligible lease is available."}
        elif args.action in ("retry", "cancel"):
            result = getattr(jobs, args.action)(args.job, args.revision)
        elif args.action == "prepare":
            result = ResearchCorpus(index).prepare(limit=args.batch_size, retry_failed=args.retry_preparation_failures)
        elif args.action == "embed":
            provider = provider_from_settings(settings)
            result = ResearchCorpus(index).embed_batch(provider, limit=args.batch_size)
        else:
            result = jobs.health()
        print(json.dumps(result))
    finally:
        if client:
            client.close()
        if database:
            database.close()
        index.close()


if __name__ == "__main__":
    main()
