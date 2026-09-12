"""Financial Statement Data Sets (FSDS): quarterly zips of sub/num/pre/tag -> Parquet.

https://www.sec.gov/dera/data/financial-statement-data-sets
The `pre` table is the as-reported presentation: which statement each line is on, and in what order.
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path

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


def _read_csv_sql(path: Path) -> str:
    return (
        f"read_csv('{path.as_posix()}', delim='\\t', header=true, quote='', escape='', "
        f"all_varchar=true, null_padding=true, ignore_errors=true, encoding='utf-8')"
    )


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
            for t in TABLES:
                src = Path(tmp) / f"{t}.txt"
                cols = [r[0] for r in duck.sql(f"DESCRIBE SELECT * FROM {_read_csv_sql(src)}").fetchall()]
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
                    f"COPY (SELECT {SELECTS[t]} FROM {_read_csv_sql(src)}{extra}) "
                    f"TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)"
                )
                counts[t] = duck.sql(f"SELECT count(*) FROM read_parquet('{target}')").fetchone()[0]
        log.info("FSDS %s loaded: %s", quarter, counts)
        return counts
    finally:
        if own:
            duck.close()


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
