"""Financial Statement Data Sets (FSDS): quarterly zips of sub/num/pre/tag -> Parquet.

https://www.sec.gov/dera/data/financial-statement-data-sets
The `pre` table is the as-reported presentation: which statement each line is on, and in what order.
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa

from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

TABLES = ("sub", "num", "pre", "tag")

# Typed projections. Files are read with all_varchar and cast here so every quarter (2009 -> now)
# lands with an identical schema regardless of columns the SEC added later.
SELECTS = {
    "sub": """
        adsh, TRY_CAST(cik AS BIGINT) AS cik, name, sic, countryba, stprba, cityba, countryinc, stprinc,
        ein, former, TRY_STRPTIME(changed, '%Y%m%d')::DATE AS changed, afs, TRY_CAST(wksi AS INTEGER) AS wksi,
        fye, form, TRY_STRPTIME(period, '%Y%m%d')::DATE AS period, TRY_CAST(fy AS INTEGER) AS fy, fp,
        TRY_STRPTIME(filed, '%Y%m%d')::DATE AS filed, TRY_CAST(prevrpt AS INTEGER) AS prevrpt,
        TRY_CAST(detail AS INTEGER) AS detail, instance, TRY_CAST(nciks AS INTEGER) AS nciks, aciks
    """,
    "num": """
        adsh, tag, version, NULLIF(coreg, '') AS coreg, TRY_STRPTIME(ddate, '%Y%m%d')::DATE AS ddate,
        TRY_CAST(qtrs AS INTEGER) AS qtrs, uom, TRY_CAST(value AS DOUBLE) AS value, footnote
    """,
    "pre": """
        adsh, TRY_CAST(report AS INTEGER) AS report, TRY_CAST(line AS INTEGER) AS line, stmt,
        TRY_CAST(inpth AS INTEGER) AS inpth, rfile, tag, version, plabel, TRY_CAST(negating AS INTEGER) AS negating
    """,
    "tag": """
        tag, version, TRY_CAST(custom AS INTEGER) AS custom, TRY_CAST(abstract AS INTEGER) AS abstract,
        datatype, iord, crdr, tlabel, doc
    """,
}

# Optional columns that only exist in some vintages; referenced only if present.
OPTIONAL = {"num": ["dimh", "iprx", "segments", "dimn"]}


REJECT_WARN_RATIO = 0.001  # more than 0.1 % of a table's rows rejected is worth a human look

LOAD_LOG_SCHEMA = pa.schema(
    [
        ("quarter", pa.string()),
        ("table", pa.string()),
        ("encoding", pa.string()),
        ("raw_rows", pa.int64()),
        ("loaded_rows", pa.int64()),
        ("rejected_rows", pa.int64()),
        ("reject_examples", pa.list_(pa.string())),
        ("unparsed_values", pa.int64()),
        ("loaded_at", pa.timestamp("s")),
    ]
)


def _read_csv_sql(path: Path, encoding: str) -> str:
    """Every column as text (typed by SELECTS), rows padded to the header width, and a row DuckDB
    cannot read at all recorded in its reject tables rather than dropped on the quiet."""
    return (
        f"read_csv('{path.as_posix()}', delim='\\t', header=true, quote='', escape='', "
        f"all_varchar=true, null_padding=true, store_rejects=true, encoding='{encoding}')"
    )


def _raw_rows(path: Path) -> int:
    """Data lines in the file (the SEC never quotes, so a newline is a row)."""
    with path.open("rb") as f:
        return max(sum(1 for _ in f) - 1, 0)


def _transcode_to_utf8(src: Path) -> Path:
    """Rewrite a file as UTF-8, line by line: a line that already is valid UTF-8 is kept as it is, any
    other line is decoded as Windows-1252, the encoding of the SEC's pre-2013 files.

    Done in Python rather than with DuckDB's `latin-1` reader because ISO-8859-1 leaves 0x80-0x9F
    undefined and DuckDB rejects them, while Windows-1252 uses exactly that range for bullets and smart
    quotes. cp1252 with `errors="replace"` cannot fail, so the re-read can only reject a row for a
    structural reason, never for its bytes.
    """
    out = src.with_suffix(".utf8.txt")
    with src.open("rb") as fin, out.open("wb") as fout:
        for raw in fin:
            try:
                raw.decode("utf-8")
                fout.write(raw)
            except UnicodeDecodeError:
                fout.write(raw.decode("cp1252", errors="replace").encode("utf-8"))
    return out


def _drain_rejects(duck: Duck) -> tuple[int, list[str], bool]:
    """(count, examples, had_encoding_errors) from DuckDB's reject tables, then clear them.
    The tables exist only once something has been rejected."""
    try:
        rows = duck.fetch_all("SELECT line, error_type, csv_line FROM reject_errors ORDER BY line LIMIT 5")
        count = duck.fetch_value("SELECT count(*) FROM reject_errors")
    except duckdb.CatalogException:
        return 0, [], False
    encoding = any(r[1] == "INVALID ENCODING" for r in rows)
    examples = [f"line {r[0]}: {r[1]}: {str(r[2])[:120]}" for r in rows]
    duck.sql("DELETE FROM reject_errors")
    duck.sql("DELETE FROM reject_scans")
    return int(count), examples, encoding


def load_fsds_quarter(storage: Storage, quarter: str, duck: Duck | None = None) -> dict[str, int]:
    """Load one quarter's four tables into fsds/{table}/quarter={quarter}/part-0.parquet (idempotent)."""
    own = duck is None
    duck = duck or Duck(storage)
    counts: dict[str, int] = {}
    try:
        with (
            storage.local_copy(layout.raw_fsds_zip(quarter)) as zpath,
            tempfile.TemporaryDirectory() as tmp,
        ):
            with zipfile.ZipFile(zpath) as zf:
                for t in TABLES:
                    zf.extract(f"{t}.txt", tmp)
            log_rows: list[dict] = []
            for t in TABLES:
                src = Path(tmp) / f"{t}.txt"
                raw_rows = _raw_rows(src)
                # The SEC's files are UTF-8 from about 2013; earlier quarters carry Windows-1252 bytes.
                # Read as UTF-8 first; only when the rejects say the bytes were the problem, transcode
                # and read again, so the second pass can only reject a row for its structure.
                encoding = "utf-8"
                for attempt in ("utf-8", "cp1252"):
                    if attempt == "cp1252":
                        src = _transcode_to_utf8(src)
                        encoding = "cp1252"
                    _drain_rejects(duck)
                    cols = duck.fetch_column(f"DESCRIBE SELECT * FROM {_read_csv_sql(src, 'utf-8')}")
                    extra = ""
                    if t == "num":
                        # Some vintages ship dimensional rows; statements only use non-dimensional values.
                        if "segments" in cols:
                            extra = " WHERE (segments IS NULL OR segments = '')"
                        elif "dimh" in cols:
                            extra = " WHERE (dimh IS NULL OR dimh = '' OR dimh = '0x00000000')"
                    out_dir = layout.fsds_table_dir(t, quarter)
                    storage.delete(out_dir)
                    storage.mkdirs(out_dir)
                    target = duck.path(f"{out_dir}/part-0.parquet")
                    duck.sql(
                        f"COPY (SELECT {SELECTS[t]} FROM {_read_csv_sql(src, 'utf-8')}{extra}) "
                        f"TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)"
                    )
                    rejected, examples, bad_encoding = _drain_rejects(duck)
                    if not bad_encoding:
                        break
                    log.info("FSDS %s %s: not valid UTF-8, transcoding from Windows-1252", quarter, t)
                loaded = duck.fetch_value(f"SELECT count(*) FROM read_parquet('{target}')")
                unparsed = _unparsed_values(duck, t, target, src, "utf-8", extra)
                counts[t] = loaded
                log_rows.append(
                    {
                        "quarter": quarter,
                        "table": t,
                        "encoding": encoding,
                        "raw_rows": raw_rows,
                        "loaded_rows": loaded,
                        "rejected_rows": rejected,
                        "reject_examples": examples,
                        "unparsed_values": unparsed,
                        "loaded_at": datetime.now(UTC).replace(tzinfo=None, microsecond=0),
                    }
                )
                if raw_rows and rejected / raw_rows > REJECT_WARN_RATIO:
                    log.warning(
                        "FSDS %s %s: %d of %d rows rejected (%.2f%%); first: %s",
                        quarter,
                        t,
                        rejected,
                        raw_rows,
                        100 * rejected / raw_rows,
                        examples[:1],
                    )
            storage.write_parquet(
                f"{layout.FSDS_LOAD_LOG}/{quarter}.parquet", pa.Table.from_pylist(log_rows, schema=LOAD_LOG_SCHEMA)
            )
        log.info("FSDS %s loaded: %s", quarter, counts)
        return counts
    finally:
        if own:
            duck.close()


def _unparsed_values(duck: Duck, table: str, target: str, src: Path, encoding: str, extra: str) -> int:
    """Rows whose key numeric/date field was present in the file but did not parse (TRY_CAST -> NULL).
    Not rejected, not silent either: they are counted into the load log."""
    checks = {
        "num": ("value", "value"),
        "sub": ("period", "period"),
        "pre": ("line", "line"),
        "tag": (None, None),
    }
    raw_col, typed_col = checks[table]
    if raw_col is None:
        return 0
    raw_present = duck.fetch_value(
        f"SELECT count(*) FROM {_read_csv_sql(src, encoding)}{extra} WHERE {raw_col} IS NOT NULL AND {raw_col} <> ''"
    )
    typed_present = duck.fetch_value(f"SELECT count(*) FROM read_parquet('{target}') WHERE {typed_col} IS NOT NULL")
    return max(int(raw_present) - int(typed_present), 0)


def load_log(storage: Storage) -> list[dict]:
    """Every FSDS table load with its row reconciliation, newest first."""
    rows: list[dict] = []
    for p in storage.glob(f"{layout.FSDS_LOAD_LOG}/*.parquet"):
        rows.extend(storage.read_parquet(p).to_pylist())
    return sorted(rows, key=lambda r: (r["quarter"], r["table"]), reverse=True)


def loaded_quarters(storage: Storage) -> list[str]:
    out = []
    for d in storage.ls(f"{layout.FSDS}/sub"):
        name = d.rsplit("/", 1)[-1]
        if name.startswith("quarter="):
            out.append(name.split("=", 1)[1])
    return sorted(out)


def raw_quarters(storage: Storage) -> list[str]:
    return sorted(p.rsplit("/", 1)[-1][:-4] for p in storage.ls(f"{layout.RAW}/fsds") if p.endswith(".zip"))


def load_all_fsds(storage: Storage, quarters: list[str] | None = None, force: bool = False) -> list[str]:
    done = set(loaded_quarters(storage))
    todo = [q for q in (quarters or raw_quarters(storage)) if force or q not in done]
    duck = Duck(storage)
    try:
        for q in todo:
            load_fsds_quarter(storage, q, duck)
    finally:
        duck.close()
    return todo
