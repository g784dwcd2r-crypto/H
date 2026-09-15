"""Step 5: the reader over real filings. The list, the offline resolver, the fetch, the harness, and
the two guarantees: every fetched filing reads cleanly, and the fixtures cannot go missing quietly."""

from datetime import date
from pathlib import Path

import httpx
import pyarrow as pa
import pytest

from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage
from filings_hub.testing import real_filings as rf
from filings_hub.testing import xbrl_fixtures as fx

FIXTURES = Path(__file__).parent / "fixtures" / "real_filings"


def _b(x) -> bytes:
    return x if isinstance(x, bytes) else x.encode()


def synthetic_files() -> dict[str, bytes]:
    """The hand-written filing, in the shape a fetched fixture has (it carries no definition linkbase)."""
    return {
        "schema": _b(fx.SCHEMA),
        "labels": _b(fx.LABELS),
        "presentation": _b(fx.PRESENTATION),
        "calculation": _b(fx.CALCULATION),
        "instance": _b(fx.INSTANCE),
    }


# -- the list ------------------------------------------------------------------------------------


def test_reader_set_is_well_formed():
    rows = rf.load_reader_set()
    assert len(rows) >= 20, "step 5 asks for about twenty"
    keys = [r["key"] for r in rows]
    assert len(keys) == len(set(keys)), "keys must be unique: they name the fixture directories"
    for r in rows:
        assert r["covers"], f"{r['key']} must say why it is awkward"
        assert r["form"] in rf.FORMS, f"{r['key']}: unexpected form {r['form']}"
        assert r["ticker"] or r["cik"], f"{r['key']} needs a ticker or a CIK"
    # the cases step 5 names beyond the golden set are all present
    covers = " ".join(r["covers"].lower() for r in rows)
    for needle in ("dimension", "discontinued", "20-f", "first year", "own labels"):
        assert needle in covers, needle


# -- the harness ---------------------------------------------------------------------------------


def test_harness_reads_the_synthetic_filing():
    rep = rf.read_filing(synthetic_files(), key="TFIN", accession="x")
    assert rep.ok, rep.errors
    assert rep.errors == []
    # the fixture plants one fact with no context on purpose (test_xbrl covers the reader skipping
    # it); the harness must surface what the reader tolerated, not hide it
    assert len(rep.warnings) == 1 and "missing context" in rep.warnings[0], rep.warnings
    assert rep.missing == ("definition",)  # the fixture has no _def; that is a fact, not a failure
    assert rep.roles >= 2 and len(rep.statements) >= 1
    assert rep.lines > 0 and rep.facts > 0 and rep.numeric > 0
    assert rep.dimensioned > 0  # the fee-income lines told apart only by a dimension
    assert all(s.unlabelled == 0 for s in rep.statements)


def test_harness_records_a_broken_file_instead_of_raising():
    files = synthetic_files()
    files["presentation"] = b"<not xml"
    rep = rf.read_filing(files, key="broken")
    assert not rep.ok
    assert any(e.startswith("presentation:") for e in rep.errors), rep.errors
    assert rep.facts > 0  # the other stages still ran: the instance was read


def test_harness_reports_an_incomplete_file_set():
    files = synthetic_files()
    del files["instance"]
    rep = rf.read_filing(files, key="partial")
    assert not rep.complete and not rep.ok
    assert "instance" in rep.missing
    assert rep.errors == []  # nothing crashed; the set is simply short


def test_format_report_names_what_broke():
    good = rf.read_filing(synthetic_files(), key="GOOD", accession="0001-24-1")
    files = synthetic_files()
    files["labels"] = b"<oops"
    bad = rf.read_filing(files, key="BAD", accession="0001-24-2")
    text = rf.format_report([good, bad])
    assert "GOOD" in text and "OK" in text
    assert "BAD: labels:" in text
    assert "1 of 2 filings read cleanly" in text


# -- the offline resolver ------------------------------------------------------------------------


def _lake(tmp_path: Path) -> Storage:
    st = Storage(str(tmp_path))
    st.write_parquet(
        layout.TICKERS,
        pa.table({"ticker": ["KO", "KO", "XYZ"], "cik": [21344, 999, 555], "is_current": [True, False, True]}),
    )
    st.write_parquet(layout.COMPANIES, pa.table({"cik": [21344, 999, 555], "name": ["Coca-Cola", "Old KO", "Xyz"]}))
    rows = [
        # accession, cik, form, filed, xbrl
        ("0001-24-1", 21344, "10-K", date(2024, 2, 20), True),  # latest 10-K
        ("0001-24-2", 21344, "10-K/A", date(2024, 6, 1), True),  # an amendment: not "10-K"
        ("0001-25-1", 21344, "10-K", date(2025, 2, 20), False),  # newer but not XBRL: skipped
        ("0001-10-1", 21344, "10-K", date(2010, 2, 26), True),  # the year-hinted one
        ("0001-24-9", 555, "10-Q", date(2024, 5, 1), True),
    ]
    for year in {r[3].year for r in rows}:
        sub = [r for r in rows if r[3].year == year]
        st.write_parquet(
            f"{layout.filings_year_dir(year)}/f.parquet",
            pa.table(
                {
                    "accession": [r[0] for r in sub],
                    "cik": [r[1] for r in sub],
                    "form": [r[2] for r in sub],
                    "filed_date": [r[3] for r in sub],
                    "is_xbrl": [r[4] for r in sub],
                }
            ),
        )
    return st


def test_resolver_picks_the_latest_xbrl_filing_of_the_form(tmp_path):
    st = _lake(tmp_path)
    rows = [
        {"key": "KO", "ticker": "KO", "cik": "", "form": "10-K", "year": "", "covers": "c"},
        {"key": "KO_2010", "ticker": "KO", "cik": "", "form": "10-K", "year": "2010", "covers": "c"},
        {"key": "BYCIK", "ticker": "", "cik": "555", "form": "10-Q", "year": "", "covers": "c"},
        {"key": "NOPE", "ticker": "NOPE", "cik": "", "form": "10-K", "year": "", "covers": "c"},
        {"key": "NOFORM", "ticker": "XYZ", "cik": "", "form": "20-F", "year": "", "covers": "c"},
    ]
    out = {r["key"]: r for r in rf.resolve_reader_set(st, rows)}
    assert out["KO"]["cik"] == 21344 and out["KO"]["name"] == "Coca-Cola"  # current owner, not the old one
    assert out["KO"]["accession"] == "0001-24-1"  # latest XBRL 10-K: not the /A, not the non-XBRL 2025
    assert out["KO_2010"]["accession"] == "0001-10-1"
    assert out["BYCIK"]["cik"] == 555 and out["BYCIK"]["accession"] == "0001-24-9"
    assert out["NOPE"]["error"] and "not in the universe" in out["NOPE"]["error"]
    assert out["NOFORM"]["error"] and "no XBRL 20-F" in out["NOFORM"]["error"]


def _small_lake(tmp_path: Path, tickers: pa.Table) -> Storage:
    """A lake whose tickers table has whatever owner flags the caller gives it."""
    st = Storage(str(tmp_path))
    st.write_parquet(layout.TICKERS, tickers)
    st.write_parquet(layout.COMPANIES, pa.table({"cik": [21344, 999], "name": ["Coca-Cola", "Old KO"]}))
    st.write_parquet(
        f"{layout.filings_year_dir(2024)}/f.parquet",
        pa.table(
            {
                "accession": ["0001-24-1", "0999-24-1"],
                "cik": [21344, 999],
                "form": ["10-K", "10-K"],
                "filed_date": [date(2024, 2, 20), date(2024, 3, 1)],
                "is_xbrl": [True, True],
            }
        ),
    )
    return st


ROW = {"key": "KO", "ticker": "KO", "cik": "", "form": "10-K", "year": "", "covers": "c"}


def test_resolver_works_on_a_tickers_table_from_before_step_2(tmp_path):
    """The real lake had no `is_current` yet (the universe is rebuilt after step 2); `is_primary` decides."""
    st = _small_lake(tmp_path, pa.table({"ticker": ["KO", "KO"], "cik": [999, 21344], "is_primary": [False, True]}))
    (out,) = rf.resolve_reader_set(st, [ROW])
    assert out["error"] is None and out["cik"] == 21344 and out["accession"] == "0001-24-1"


def test_resolver_works_with_no_owner_flags_at_all(tmp_path):
    st = _small_lake(tmp_path, pa.table({"ticker": ["KO"], "cik": [21344]}))
    (out,) = rf.resolve_reader_set(st, [ROW])
    assert out["error"] is None and out["cik"] == 21344


def test_resolver_on_an_empty_lake_reports_rather_than_guesses(tmp_path):
    out = rf.resolve_reader_set(Storage(str(tmp_path)), [{"key": "KO", "ticker": "KO", "cik": "", "form": "10-K"}])
    assert out[0]["error"] and out[0]["accession"] is None


# -- the fetch, through a fake SEC ---------------------------------------------------------------

BASE = "tfin-20260630"
EMPTY_DEF = b'<?xml version="1.0"?><link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"/>'


def _served() -> dict[str, bytes]:
    return {
        f"{BASE}.xsd": _b(fx.SCHEMA),
        f"{BASE}_lab.xml": _b(fx.LABELS),
        f"{BASE}_pre.xml": _b(fx.PRESENTATION),
        f"{BASE}_cal.xml": _b(fx.CALCULATION),
        f"{BASE}_def.xml": EMPTY_DEF,
        f"{BASE}_htm.xml": _b(fx.INSTANCE),
        f"{BASE}.htm": b"<html>the document</html>",
        "FilingSummary.xml": b"<x/>",
        "ex-311.htm": b"<html/>",
    }


def _index_html(cik: int, acc: str, names: list[str]) -> str:
    folder = f"/Archives/edgar/data/{cik}/{acc.replace('-', '')}"
    trs = "".join(
        f"<tr><td scope='row'>{i}</td><td scope='row'>doc</td><td scope='row'><a href='{folder}/{n}'>{n}</a></td>"
        f"<td scope='row'>EX-101</td><td scope='row'>10</td></tr>"
        for i, n in enumerate(names, 1)
    )
    return (
        "<html><body><div id='formDiv'><table class='tableFile' summary='Document Format Files'>"
        "<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>"
        + trs
        + "</table></div></body></html>"
    )


def test_fetch_writes_the_gzipped_file_set_and_a_manifest(tmp_path):
    cik, acc = 1539638, "0001539638-26-000042"
    served = _served()

    def handler(request: httpx.Request) -> httpx.Response:
        name = str(request.url).rsplit("/", 1)[-1]
        if name == f"{acc}-index.htm":
            return httpx.Response(200, text=_index_html(cik, acc, list(served)))
        if name in served:
            return httpx.Response(200, content=served[name])
        return httpx.Response(404)

    row = {
        "key": "TFIN",
        "ticker": "TFIN",
        "cik": cik,
        "name": "Triumph Financial",
        "form": "10-Q",
        "year": "",
        "accession": acc,
        "filed_date": "2026-07-30",
        "covers": "fee income by dimension",
    }
    with EdgarClient("Test test@example.com", transport=httpx.MockTransport(handler)) as client:
        target = rf.fetch_fixture(client, tmp_path, row)

    assert target == tmp_path / "TFIN"
    manifest, files = rf.load_fixture(target)
    assert set(manifest["files"]) == set(rf.FILE_ROLES) and manifest["missing"] == []
    assert manifest["accession"] == acc and manifest["cik"] == cik
    assert manifest["files"]["instance"] == f"{BASE}_htm.xml.gz"  # the extracted instance, not FilingSummary
    assert files["instance"] == _b(fx.INSTANCE)  # gzip round-trips the bytes exactly
    assert sorted(p.name for p in target.glob("*.gz")) == sorted(
        f"{n}.gz" for n in served if n.startswith(BASE) and n != f"{BASE}.htm"
    )
    # and what was fetched reads cleanly through the harness
    rep = rf.read_filing(files, key=manifest["key"], accession=manifest["accession"])
    assert rep.ok and rep.missing == (), rep.errors
    assert rf.fixture_dirs(tmp_path) == [target]


# -- the two guarantees over the real fixtures ---------------------------------------------------


@pytest.mark.parametrize("fixture", rf.fixture_dirs(FIXTURES), ids=lambda p: p.name)
def test_every_real_filing_reads_cleanly(fixture: Path):
    manifest, files = rf.load_fixture(fixture)
    rep = rf.read_filing(files, key=manifest["key"], accession=manifest.get("accession"))
    assert rep.ok, "\n".join(
        [f"{manifest['key']} ({manifest.get('accession')}): {manifest.get('covers')}", *rep.errors, *rep.warnings]
    )


@pytest.mark.xfail(
    strict=True,
    reason="the real filings are fetched on a machine that reaches EDGAR (filings-hub reader-fetch); "
    "strict, so this flips to a hard failure the moment the fixtures land and the marker must come off",
)
def test_real_filing_fixtures_are_present():
    """The step's guarantee: the twenty cannot quietly stop being tested. Red until they are fetched."""
    have = {p.name for p in rf.fixture_dirs(FIXTURES)}
    missing = [r["key"] for r in rf.load_reader_set() if r["key"] not in have]
    assert not missing, (
        f"{len(missing)} of {len(rf.load_reader_set())} real filings have no fixture under {FIXTURES}: "
        f"{', '.join(missing)}. Run `filings-hub reader-fetch` on a machine that reaches EDGAR and commit the result."
    )


def test_harness_reads_a_filing_whose_linkbases_live_in_the_schema():
    """Two files on EDGAR, four linkbases embedded: what the fetch found for MSFT, PLD, RY and TM."""
    files = {"schema": fx.embedded_schema(), "instance": _b(fx.INSTANCE)}
    rep = rf.read_filing(files, key="MSFT-shaped")
    assert rep.ok, rep.errors
    assert rep.missing == ("labels", "presentation", "calculation", "definition")  # the files, truthfully
    assert rep.embedded == ("labels", "presentation", "calculation")  # where they actually were
    assert rep.lines > 0 and rep.calc_arcs > 0
    assert all(s.unlabelled == 0 for s in rep.statements)
    text = rf.format_report([rep])
    assert "in schema" in text and "labels, presentation, calculation" in text
