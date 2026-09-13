"""Facts: companyfacts JSON -> facts/cik={cik}/part-0.parquet, one partition per company.

Dedupe rule: the same (concept, unit, period_start, period_end) reported in several filings keeps the
*latest filed* as `is_current = true`; every reported value stays in the table (restatement history).
"""

from __future__ import annotations

import logging
import re
import zipfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any

import duckdb
import orjson
import pyarrow as pa

from filings_hub.lake import layout
from filings_hub.lake.duck import to_arrow
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

CIK_FILE_RE = re.compile(r"^CIK(\d{10})\.json$")

FACTS_SCHEMA = pa.schema(
    [
        ("cik", pa.int64()),
        ("taxonomy", pa.string()),
        ("concept", pa.string()),
        ("unit", pa.string()),
        ("period_start", pa.date32()),
        ("period_end", pa.date32()),
        ("value", pa.float64()),
        ("accession", pa.string()),
        ("fy", pa.int32()),
        ("fp", pa.string()),
        ("form", pa.string()),
        ("filed", pa.date32()),
        ("frame", pa.string()),
        ("duration_days", pa.int32()),
        ("duration_kind", pa.string()),
        ("is_current", pa.bool_()),
        ("label", pa.string()),
    ]
)

DURATION_KINDS_SQL = """
CASE
  WHEN period_start IS NULL THEN 'instant'
  WHEN duration_days BETWEEN 80 AND 100 THEN 'quarter'
  WHEN duration_days BETWEEN 170 AND 190 THEN 'half_year'
  WHEN duration_days BETWEEN 260 AND 280 THEN 'nine_month'
  WHEN duration_days BETWEEN 350 AND 380 THEN 'annual'
  ELSE 'other'
END
"""


def duration_kind(days: int | None) -> str:
    """Python twin of DURATION_KINDS_SQL (kept in sync by tests)."""
    if days is None:
        return "instant"
    if 80 <= days <= 100:
        return "quarter"
    if 170 <= days <= 190:
        return "half_year"
    if 260 <= days <= 280:
        return "nine_month"
    if 350 <= days <= 380:
        return "annual"
    return "other"


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def parse_companyfacts(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a companyfacts JSON document into raw fact rows (no dedupe yet)."""
    cik = int(data["cik"])
    rows: list[dict[str, Any]] = []
    for taxonomy, concepts in (data.get("facts") or {}).items():
        for concept, body in concepts.items():
            label = body.get("label")
            for unit, entries in (body.get("units") or {}).items():
                for e in entries:
                    val = e.get("val")
                    if val is None or (isinstance(val, str) and not _is_number(val)):
                        continue
                    end = _date(e.get("end"))
                    if end is None:
                        continue
                    start = _date(e.get("start"))
                    fy = e.get("fy")
                    rows.append(
                        {
                            "cik": cik,
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "unit": unit,
                            "period_start": start,
                            "period_end": end,
                            "value": float(val),
                            "accession": e.get("accn"),
                            "fy": int(fy) if fy not in (None, "") else None,
                            "fp": e.get("fp"),
                            "form": e.get("form"),
                            "filed": _date(e.get("filed")),
                            "frame": e.get("frame"),
                            "duration_days": (end - start).days if start else None,
                            "duration_kind": None,
                            "is_current": None,
                            "label": label,
                        }
                    )
    return rows


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def finalize_facts(raw: pa.Table, con: duckdb.DuckDBPyConnection | None = None) -> pa.Table:
    """Add duration_kind and is_current via DuckDB window functions."""
    if raw.num_rows == 0:
        return FACTS_SCHEMA.empty_table()
    own = con is None
    con = con or duckdb.connect()
    try:
        con.register("raw_facts", raw)
        out = to_arrow(
            con.execute(
                f"""
            SELECT cik, taxonomy, concept, unit, period_start, period_end, value, accession, fy, fp, form,
                   filed, frame, duration_days,
                   {DURATION_KINDS_SQL} AS duration_kind,
                   row_number() OVER (
                       PARTITION BY taxonomy, concept, unit, period_start, period_end
                       ORDER BY filed DESC NULLS LAST, accession DESC
                   ) = 1 AS is_current,
                   label
            FROM raw_facts
            ORDER BY taxonomy, concept, unit, period_end, period_start, filed
            """
            )
        )
        con.unregister("raw_facts")
        return out.cast(FACTS_SCHEMA)
    finally:
        if own:
            con.close()


def write_cik_facts(storage: Storage, cik: int, table: pa.Table) -> None:
    storage.replace_dir_with_parquet(layout.facts_cik_dir(cik), table)


def load_companyfacts_json(storage: Storage, data: dict[str, Any], con: duckdb.DuckDBPyConnection | None = None) -> int:
    cik = int(data["cik"])
    table = finalize_facts(pa.Table.from_pylist(parse_companyfacts(data), schema=FACTS_SCHEMA), con)
    write_cik_facts(storage, cik, table)
    return table.num_rows


# ---------------------------------------------------------------------------------------------
# Bulk zip
# ---------------------------------------------------------------------------------------------
def _process_names(args: tuple[str, str, list[str]]) -> tuple[int, int, list[str]]:
    zip_path, lake_root, names = args
    storage = Storage(lake_root)
    con = duckdb.connect()
    n_rows = n_ciks = 0
    failures: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in names:
            try:
                data = orjson.loads(zf.read(name))
                if not data.get("cik"):
                    data["cik"] = int(CIK_FILE_RE.match(name).group(1))  # type: ignore[union-attr]
                n_rows += load_companyfacts_json(storage, data, con)
                n_ciks += 1
            except Exception as e:
                failures.append(f"{name}: {e}")
    con.close()
    return n_ciks, n_rows, failures


def load_bulk_companyfacts(storage: Storage, zip_rel: str, workers: int = 4, batch: int = 200) -> dict[str, Any]:
    """Rebuild facts/ from companyfacts.zip using a process pool (JSON parsing is CPU bound)."""
    with storage.local_copy(zip_rel) as local:
        with zipfile.ZipFile(str(local)) as zf:
            names = [n for n in zf.namelist() if CIK_FILE_RE.match(n)]
        batches = [names[i : i + batch] for i in range(0, len(names), batch)]
        total_ciks = total_rows = 0
        failures: list[str] = []
        if workers <= 1:
            for b in batches:
                c, r, f = _process_names((str(local), storage.root, b))
                total_ciks, total_rows = total_ciks + c, total_rows + r
                failures.extend(f)
                log.info("facts: %d companies, %d rows", total_ciks, total_rows)
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(_process_names, (str(local), storage.root, b)) for b in batches]
                for fut in as_completed(futs):
                    c, r, f = fut.result()
                    total_ciks, total_rows = total_ciks + c, total_rows + r
                    failures.extend(f)
                    log.info("facts: %d companies, %d rows", total_ciks, total_rows)
    if failures:
        log.warning("facts: %d companies failed: %s", len(failures), failures[:5])
    return {"companies": total_ciks, "rows": total_rows, "failures": failures}


def load_api_companyfacts(storage: Storage, client, ciks: list[int], day: date, workers: int = 4) -> dict[str, Any]:
    """Fallback for a missing companyfacts.zip: fetch every company from the per-company API.

    The client's rate limiter (10 req/s) is the bottleneck, so threads are enough; each fetch also
    stores the raw response like the refresh path does. Returns the same shape as the bulk loader.
    """
    total_rows = total_ciks = 0
    failures: list[str] = []
    done = 0

    reused = 0

    def one(cik: int) -> int:
        nonlocal reused
        try:
            have = _stored_facts_rows(storage, cik, day)
            if have is not None:  # a rerun the same day: the partition is already built from this response
                reused += 1
                return have
            return refresh_cik_facts(storage, client, cik, day)
        except Exception as e:  # one company must not sink the run
            raise RuntimeError(f"CIK {cik}: {e}") from e

    log.info("facts: companyfacts.zip unavailable; fetching %d companies from the API", len(ciks))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for fut in as_completed([pool.submit(one, cik) for cik in ciks]):
            done += 1
            try:
                rows = fut.result()
            except Exception as e:
                failures.append(f"companyfacts api: {e}")
                continue
            if rows:
                total_ciks += 1
                total_rows += rows
            if done % 500 == 0 or done == len(ciks):
                log.info("facts (api): %d/%d companies fetched, %d rows", done, len(ciks), total_rows)
    if reused:
        log.info("facts (api): %d companies reused today's stored response (no refetch)", reused)
    if failures:
        log.warning("facts (api): %d companies failed: %s", len(failures), failures[:5])
    return {"companies": total_ciks, "rows": total_rows, "failures": failures}


def refresh_cik_facts(storage: Storage, client, cik: int, day: date) -> int:
    """Per-company API path; stores the raw response, then rewrites the CIK partition."""
    data = client.fetch_companyfacts(cik)
    if not data or not data.get("facts"):
        log.debug("no companyfacts for CIK %s", cik)
        return 0
    data.setdefault("cik", cik)  # a handful of responses omit it
    storage.write_bytes(layout.raw_api_companyfacts(day, cik), orjson.dumps(data))
    return load_companyfacts_json(storage, data)


def _stored_facts_rows(storage: Storage, cik: int, day: date) -> int | None:
    """Row count of an already-built partition whose API response was stored on `day`, else None."""
    part = f"{layout.facts_cik_dir(cik)}/part-0.parquet"
    if not (storage.exists(layout.raw_api_companyfacts(day, cik)) and storage.exists(part)):
        return None
    import pyarrow.parquet as pq

    with storage.open(part, "rb") as fh:
        return pq.read_metadata(fh).num_rows
