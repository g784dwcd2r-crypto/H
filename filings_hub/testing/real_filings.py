"""Step 5: run the XBRL reader over real filings, and keep them as permanent tests.

Every reader test until now used a filing we wrote ourselves (`xbrl_fixtures`). Real filings are
messier. This module holds the three pieces that turn about twenty awkward real filings into tests
that can never break silently:

* `reader_set.csv` says which filings, and why each is awkward: the golden set (the twenty the
  acceptance criteria already watch) plus the cases step 5 names that it lacks.
* `resolve_reader_set` and `fetch_fixture` turn a row into an accession, offline from the lake's own
  `tickers` and `filings` tables, then download its five XBRL files from EDGAR, gzipped, with a
  manifest. They run where EDGAR is reachable (`filings-hub reader-fetch`).
* `read_filing` and `format_report` are the harness: run the whole reader pipeline over one filing
  and write down everything that breaks, rather than stopping at the first thing
  (`filings-hub reader-check`). `tests/test_real_filings.py` runs it over every fetched fixture.
"""

from __future__ import annotations

import csv
import gzip
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from filings_hub.ingest import xbrl
from filings_hub.ingest.documents import document_url, filing_index_url, parse_filing_index
from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
READER_SET_CSV = DATA_DIR / "reader_set.csv"
MANIFEST = "manifest.json"
FILE_ROLES = ("instance", "schema", "labels", "presentation", "calculation", "definition")
# Enough to build a statement, mirroring FileSet.is_complete: the facts, the order, and the words.
REQUIRED_ROLES = ("instance", "presentation", "labels")
FORMS = ("10-K", "10-Q", "20-F", "40-F")


def load_reader_set(path: Path | None = None) -> list[dict[str, str]]:
    with (path or READER_SET_CSV).open() as f:
        return [r for r in csv.DictReader(f) if r.get("key")]


def _int_or_none(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


# -- resolving and fetching: run where EDGAR is reachable --------------------------------------


def resolve_reader_set(storage: Storage, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Each row's accession, found offline in the lake.

    Ticker to CIK the way `verify` does it: the current owner of a reused ticker first (step 2), or
    the primary listing on a tickers table from before step 2. Then
    the latest XBRL filing of that form, or the latest one filed in `year` when set. A row given
    by CIK skips the ticker lookup. A row that cannot be resolved comes back with `error` set rather
    than a guessed filing."""
    duck = Duck(storage)
    try:
        have_tickers = duck.view("tickers", layout.TICKERS, hive=False)
        have_companies = duck.view("companies", layout.COMPANIES, hive=False)
        have_filings = duck.view("filings", f"{layout.FILINGS}/*/*.parquet")
        # `is_current` (step 2) exists only once the universe has been rebuilt; an older tickers table
        # carries `is_primary` alone. Order by whichever owner flags are there; never fail for the lack.
        owner_flags: list[str] = []
        if have_tickers:
            cols = {r["column_name"] for r in duck.fetch_dicts("DESCRIBE tickers")}
            owner_flags = [c for c in ("is_current", "is_primary") if c in cols]
        owner_order = (" ORDER BY " + ", ".join(f"({c} IS TRUE) DESC" for c in owner_flags)) if owner_flags else ""
        out: list[dict[str, Any]] = []
        for row in rows:
            r: dict[str, Any] = {
                **row,
                "cik": _int_or_none(row.get("cik")),
                "accession": None,
                "filed_date": None,
                "name": None,
                "error": None,
            }
            if r["cik"] is None:
                if not have_tickers:
                    r["error"] = "no tickers table in the lake"
                    out.append(r)
                    continue
                hit = duck.fetch_dicts(
                    f"SELECT cik FROM tickers WHERE ticker = ?{owner_order} LIMIT 1",
                    [(row.get("ticker") or "").upper()],
                )
                if not hit:
                    r["error"] = f"ticker {row.get('ticker')} not in the universe"
                    out.append(r)
                    continue
                r["cik"] = int(hit[0]["cik"])
            if have_companies:
                name = duck.fetch_dicts("SELECT name FROM companies WHERE cik = ? LIMIT 1", [r["cik"]])
                r["name"] = name[0]["name"] if name else None
            if not have_filings:
                r["error"] = "no filings table in the lake"
                out.append(r)
                continue
            year = _int_or_none(row.get("year"))
            hit = duck.fetch_dicts(
                "SELECT accession, filed_date FROM filings "
                "WHERE cik = ? AND form = ? AND is_xbrl AND (? IS NULL OR year(filed_date) = ?) "
                "ORDER BY filed_date DESC LIMIT 1",
                [r["cik"], row["form"], year, year],
            )
            if not hit:
                r["error"] = f"no XBRL {row['form']} filing" + (f" filed in {year}" if year else "")
            else:
                r["accession"] = hit[0]["accession"]
                r["filed_date"] = str(hit[0]["filed_date"])
            out.append(r)
        return out
    finally:
        duck.close()


def fetch_fixture(client: EdgarClient, out_dir: Path, row: dict[str, Any]) -> Path:
    """Download one filing's XBRL file set into `out_dir/<key>/`, gzipped, with a manifest.

    Never guesses a filename: the filing's own index page says what it bundles and `file_set` picks
    the five out of it. A file the filing does not have is recorded as missing, not invented."""
    cik, accession = int(row["cik"]), row["accession"]
    index = parse_filing_index(client.get(filing_index_url(cik, accession)).text)
    found = xbrl.file_set([d["filename"] for d in index if d.get("filename")])
    target = out_dir / row["key"]
    target.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for role in FILE_ROLES:
        name = getattr(found, role)
        if not name:
            continue
        data = client.get(document_url(cik, accession, name)).content
        (target / f"{name}.gz").write_bytes(gzip.compress(data))
        files[role] = f"{name}.gz"
    manifest = {
        k: row.get(k) for k in ("key", "ticker", "cik", "name", "form", "year", "accession", "filed_date", "covers")
    }
    manifest["files"] = files
    manifest["missing"] = list(found.missing)
    (target / MANIFEST).write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    return target


# -- the harness: runs anywhere -----------------------------------------------------------------


def fixture_dirs(root: Path) -> list[Path]:
    """Every fetched fixture under `root`, by key."""
    return sorted(p.parent for p in root.glob(f"*/{MANIFEST}")) if root.exists() else []


def load_fixture(fixture_dir: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    manifest = json.loads((fixture_dir / MANIFEST).read_text())
    files = {role: gzip.decompress((fixture_dir / name).read_bytes()) for role, name in manifest["files"].items()}
    return manifest, files


@dataclass
class StatementReport:
    kind: str
    title: str
    lines: int
    unlabelled: int  # lines the reader could not put a label on: the company's words are missing


@dataclass
class ReaderReport:
    """Everything the reader found, and everything that broke, for one filing."""

    key: str
    accession: str | None
    complete: bool = False
    missing: tuple[str, ...] = ()
    roles: int = 0
    statements: list[StatementReport] = field(default_factory=list)
    facts: int = 0
    numeric: int = 0
    dimensioned: int = 0
    contexts: int = 0
    units: int = 0
    calc_arcs: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def lines(self) -> int:
        return sum(s.lines for s in self.statements)

    @property
    def ok(self) -> bool:
        """Read cleanly: nothing raised, the three files a statement needs were there, at least one
        statement came out with lines on it, and the instance carried facts."""
        return not self.errors and self.complete and self.lines > 0 and self.facts > 0


class _WarningCapture(logging.Handler):
    """The reader logs what it tolerates (a presentation cycle it broke); we keep those as findings."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _call(rep: ReaderReport, what: str, fn: Any, *args: Any) -> Any:
    """Run one stage; a failure is written down against the stage and the rest still runs."""
    try:
        return fn(*args)
    except Exception as e:  # the point is to record every kind of break
        rep.errors.append(f"{what}: {type(e).__name__}: {e}")
        return None


def read_filing(files: dict[str, bytes], key: str = "", accession: str | None = None) -> ReaderReport:
    """Run the whole reader pipeline over one filing's files and report, never raise."""
    rep = ReaderReport(key=key, accession=accession)
    rep.missing = tuple(r for r in FILE_ROLES if r not in files)
    rep.complete = all(r in files for r in REQUIRED_ROLES)
    capture = _WarningCapture()
    xbrl.log.addHandler(capture)
    try:
        labels = (_call(rep, "labels", xbrl.parse_labels, files["labels"]) if "labels" in files else None) or {}
        pre = (
            _call(rep, "presentation", xbrl.parse_presentation, files["presentation"])
            if "presentation" in files
            else None
        ) or ()
        cal = (
            _call(rep, "calculation", xbrl.parse_calculation, files["calculation"]) if "calculation" in files else None
        ) or ()
        if "definition" in files:
            _call(rep, "definition", xbrl.parse_definition, files["definition"])
        defs = (_call(rep, "schema", xbrl.parse_role_definitions, files["schema"]) if "schema" in files else None) or {}
        rep.roles = len(defs)
        rep.calc_arcs = len(cal)
        for role in xbrl.statement_roles(defs):
            lines = _call(rep, f"presentation tree: {role.title}", xbrl.presentation_tree, pre, role.role, labels) or []
            rep.statements.append(
                StatementReport(role.kind, role.title, len(lines), sum(1 for ln in lines if ln.label is None))
            )
        inst = _call(rep, "instance", xbrl.parse_instance, files["instance"]) if "instance" in files else None
        if inst is not None:
            rep.facts = len(inst.facts)
            rep.numeric = sum(1 for f in inst.facts if f.number is not None)
            rep.contexts = len(inst.contexts)
            rep.units = len(inst.units)
            rep.dimensioned = sum(1 for _, c in xbrl.iter_facts(inst) if c.is_dimensioned)
    finally:
        xbrl.log.removeHandler(capture)
    rep.warnings = capture.messages
    if rep.complete and "schema" in files and not rep.statements:
        rep.errors.append("no statement roles found in the schema")
    return rep


def format_report(reports: list[ReaderReport]) -> str:
    out = [f"  {'key':<10} {'accession':<22} {'result':<7} {'stmts':>5} {'lines':>6} {'facts':>7} {'dims':>6}  missing"]
    for r in reports:
        out.append(
            f"  {r.key:<10} {(r.accession or ''):<22} {'OK' if r.ok else 'BROKEN':<7} "
            f"{len(r.statements):>5} {r.lines:>6} {r.facts:>7} {r.dimensioned:>6}  {', '.join(r.missing) or '-'}"
        )
    broken = [r for r in reports if r.errors or r.warnings or not r.ok]
    if broken:
        out += ["", "What broke:"]
        for r in broken:
            for e in r.errors:
                out.append(f"  {r.key}: {e}")
            for w in r.warnings:
                out.append(f"  {r.key}: warning: {w}")
            if not r.errors and not r.ok:
                why = "no statement lines" if r.lines == 0 else "no facts" if r.facts == 0 else "incomplete file set"
                out.append(f"  {r.key}: {why}")
    clean = sum(1 for r in reports if r.ok)
    out += ["", f"{clean} of {len(reports)} filings read cleanly"]
    return "\n".join(out)
