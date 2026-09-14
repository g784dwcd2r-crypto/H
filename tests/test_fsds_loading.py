"""FSDS loading must never drop a row silently: every table load is reconciled and logged."""

from __future__ import annotations

import io
import zipfile
from datetime import date

from filings_hub.ingest import fsds
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx


def _zip_with(tables: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for t, data in tables.items():
            zf.writestr(f"{t}.txt", data)
    return buf.getvalue()


def _base_tables() -> dict[str, bytes]:
    q = fx.fsds_quarters()["2026q1"]
    return {t: text.encode("utf-8") for t, text in q.items()}


def _load(tmp_path, tables: dict[str, bytes], quarter="2026q1"):
    st = Storage(str(tmp_path / "lake"))
    st.write_bytes(layout.raw_fsds_zip(quarter), _zip_with(tables))
    counts = fsds.load_fsds_quarter(st, quarter)
    log = {r["table"]: r for r in fsds.load_log(st)}
    return st, counts, log


def test_clean_quarter_reconciles_exactly(tmp_path):
    _st, counts, log = _load(tmp_path, _base_tables())
    for t in ("sub", "num", "pre", "tag"):
        assert log[t]["raw_rows"] == log[t]["loaded_rows"] == counts[t], t
        assert log[t]["rejected_rows"] == 0 and log[t]["unparsed_values"] == 0
        assert log[t]["encoding"] == "utf-8"


def test_pre_2013_windows_1252_bytes_are_read_not_dropped(tmp_path):
    """Early quarters carry Latin-1 / Windows-1252 bytes in labels (a bullet, an accented name).
    Reading them as UTF-8 rejects the row; the loader must fall back, not lose the line."""
    tables = _base_tables()
    pre = tables["pre"].decode("utf-8").splitlines()
    # a label with a Windows-1252 byte: 'Caf\xe9' and a bullet '\x95'
    pre.append("0000019617-26-000001\t2\t12\tIS\t0\tH\tNetIncomeLossCafe\tus-gaap/2025\tCaf\xe9 \x95 net\t0")
    tables["pre"] = ("\n".join(pre) + "\n").encode("latin-1")
    st, _counts, log = _load(tmp_path, tables)
    assert log["pre"]["encoding"] == "cp1252"
    assert log["pre"]["rejected_rows"] == 0
    assert log["pre"]["loaded_rows"] == log["pre"]["raw_rows"]
    duck = Duck(st)
    try:
        duck.view("fsds_pre", f"{layout.FSDS}/pre/*/*.parquet")
        label = duck.fetch_value("SELECT plabel FROM fsds_pre WHERE tag = 'NetIncomeLossCafe'")
    finally:
        duck.close()
    assert label == "Café • net"  # the bullet is 0x95 in Windows-1252, undefined in ISO-8859-1


def test_unparseable_values_are_counted_not_hidden(tmp_path):
    tables = _base_tables()
    num = tables["num"].decode().splitlines()
    num.append("0000019617-26-000001\tAssets\tus-gaap/2025\t20251231\t0\tUSD\t\t\tN/A\t")  # value not a number
    num.append("0000019617-26-000001\tAssets\tus-gaap/2025\tnot-a-date\t0\tUSD\t\t\t5\t")  # still loads: ddate NULL
    tables["num"] = ("\n".join(num) + "\n").encode()
    _st, _counts, log = _load(tmp_path, tables)
    assert log["num"]["loaded_rows"] == log["num"]["raw_rows"]  # nothing rejected
    assert log["num"]["unparsed_values"] == 1  # but the N/A value was noticed


def test_load_log_persists_per_quarter_and_lists_newest_first(tmp_path):
    st, _, _ = _load(tmp_path, _base_tables(), quarter="2025q4")
    st.write_bytes(layout.raw_fsds_zip("2026q1"), _zip_with(_base_tables()))
    fsds.load_fsds_quarter(st, "2026q1")
    rows = fsds.load_log(st)
    assert [r["quarter"] for r in rows][:4] == ["2026q1"] * 4
    assert {(r["quarter"], r["table"]) for r in rows} == {(q, t) for q in ("2025q4", "2026q1") for t in fsds.TABLES}
    assert all(r["loaded_at"].year >= 2026 for r in rows)
    # reloading a quarter replaces its log rather than appending to it
    fsds.load_fsds_quarter(st, "2026q1")
    assert len(fsds.load_log(st)) == 8


def test_reject_ratio_warning(tmp_path, caplog):
    """A quarter where a meaningful share of rows cannot be read is flagged for a human."""
    import logging

    tables = _base_tables()
    # rows with an embedded NUL byte cannot be read as text at all
    bad = b"\n".join(b"0000019617-26-000001\tX\x00Y\tus-gaap/2025\t20251231\t0\tUSD\t\t\t1\t" for _ in range(50))
    tables["num"] = tables["num"] + bad + b"\n"
    with caplog.at_level(logging.WARNING, logger="filings_hub.ingest.fsds"):
        _st, _counts, log = _load(tmp_path, tables)
    # whichever way DuckDB treats the bytes, the accounting must balance: raw = loaded + rejected
    assert log["num"]["raw_rows"] == log["num"]["loaded_rows"] + log["num"]["rejected_rows"]
    if log["num"]["rejected_rows"]:
        assert any("rejected" in r.message for r in caplog.records)
        assert log["num"]["reject_examples"]


def test_raw_row_counter():
    import tempfile
    from pathlib import Path

    p = Path(tempfile.mkdtemp()) / "t.txt"
    p.write_bytes(b"h1\th2\n1\t2\n3\t4\n")
    assert fsds._raw_rows(p) == 2
    p.write_bytes(b"h1\th2\n")
    assert fsds._raw_rows(p) == 0
    assert date.today()  # keep the import honest for the fixtures module


def test_quoted_tab_lines_are_rejoined_not_rejected(tmp_path):
    """The SEC's writer wraps a value holding a tab in double quotes (an investment name in `segments`,
    a footnote). Read with quotes off, that line has one field too many and DuckDB rejects it. The
    loader must re-join the quoted run so the row loads, and count what it repaired."""
    tables = _base_tables()
    num = tables["num"].decode().splitlines()
    # a dimensional row (schedule of investments) with a tab inside the quoted segments value
    num.append(
        "0000019617-26-000001\tInvestmentOwnedBalancePrincipalAmount\tus-gaap/2025\t20251231\t0\tUSD"
        '\t"InvestmentIdentifier=GC3262\tDili Corp;"\t\t2500000\t'
    )
    # a plain statement row with a tab inside a quoted footnote: the number must land intact
    num.append(
        '0000019617-26-000001\tOtherAssetsNoncurrent\tus-gaap/2025\t20251231\t0\tUSD\t\t\t4200000\t"see note\t7"'
    )
    tables["num"] = ("\n".join(num) + "\n").encode()
    st, _counts, log = _load(tmp_path, tables)
    assert log["num"]["repaired_rows"] == 2
    assert log["num"]["rejected_rows"] == 0
    duck = Duck(st)
    try:
        duck.view("fsds_num", f"{layout.FSDS}/num/*/*.parquet")
        row = duck.fetch_all("SELECT value, footnote FROM fsds_num WHERE tag = 'OtherAssetsNoncurrent'")
        assert row == [(4200000.0, "see note 7")]
        # the dimensional row is loaded too, flagged, with its segments text intact
        seg = duck.fetch_all(
            "SELECT dimensional, segments FROM fsds_num WHERE tag = 'InvestmentOwnedBalancePrincipalAmount'"
        )
        assert seg == [(True, "InvestmentIdentifier=GC3262 Dili Corp;")]
    finally:
        duck.close()


def test_rejoin_quoted_fields_shapes():
    j = fsds._rejoin_quoted_fields
    assert j([b"a", b'"x', b'y"', b"c"], 3) == [b"a", b"x y", b"c"]
    assert j([b"a", b'"x', b"mid", b'y"'], 2) == [b"a", b"x mid y"]
    assert j([b"a", b'"x', b"y"], 2) is None  # never closed
    assert j([b"a", b"b", b"c"], 2) is None  # nothing quoted to explain the overflow
    assert j([b'"whole"', b"b", b"c"], 3) == [b'"whole"', b"b", b"c"]  # a quoted field with no tab is left as is


def test_every_row_and_column_of_the_file_is_kept(tmp_path):
    """Nothing the SEC publishes is dropped: dimensional `num` rows (segment, geography, one investment
    of a fund) load with a `dimensional` flag; columns outside the typed core (`sub` addresses, `segments`,
    a column the SEC adds in a later vintage) pass through as text."""
    tables = _base_tables()
    num = tables["num"].decode().splitlines()
    num[0] += "\tnewcol"  # a column this loader has never heard of
    num = [line + "\t" for line in num[:1]] + [line + "\tx" for line in num[1:]]
    num.append(
        "0000019617-26-000001\tRevenues\tus-gaap/2025\t20251231\t4\tUSD"
        "\tStatementBusinessSegmentsAxis=ConsumerBankingMember;\t\t1000\t\ty"
    )
    tables["num"] = ("\n".join(num) + "\n").encode()
    st, _counts, log = _load(tmp_path, tables)
    assert log["num"]["loaded_rows"] == log["num"]["raw_rows"]
    assert log["num"]["rejected_rows"] == 0
    duck = Duck(st)
    try:
        duck.view("fsds_num", f"{layout.FSDS}/num/*/*.parquet")
        duck.view("fsds_sub", f"{layout.FSDS}/sub/*/*.parquet")
        cols = set(duck.fetch_column("SELECT column_name FROM (DESCRIBE fsds_num)"))
        assert {"segments", "dimensional", "newcol", "value", "ddate"} <= cols
        assert duck.fetch_value("SELECT count(*) FROM fsds_num WHERE dimensional") == 1
        assert duck.fetch_value("SELECT newcol FROM fsds_num WHERE dimensional") == "y"
        assert duck.fetch_value("SELECT segments FROM fsds_num WHERE dimensional") == (
            "StatementBusinessSegmentsAxis=ConsumerBankingMember;"
        )
        sub_cols = set(duck.fetch_column("SELECT column_name FROM (DESCRIBE fsds_sub)"))
        assert {"zipba", "bas1", "baph", "cityma", "cik", "period"} <= sub_cols
    finally:
        duck.close()
