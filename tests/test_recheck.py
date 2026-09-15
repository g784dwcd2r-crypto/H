"""`recheck`: the arithmetic checks recomputed from the lake, identical to the build's, in minutes."""

from filings_hub.ingest import checks as chk
from filings_hub.ingest import sync_statements as S
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage

COLS = "accession, cik, statement, check_name, passed, lhs, rhs, difference, detail, source"


def _all_checks(st: Storage) -> list[tuple]:
    duck = Duck(st)
    try:
        if not duck.view("sc", f"{layout.STATEMENT_CHECKS}/*/*.parquet"):
            return []
        return duck.fetch_all(f"SELECT {COLS} FROM sc ORDER BY accession, cik, statement, check_name, source")
    finally:
        duck.close()


def _check_files(st: Storage) -> list[str]:
    return sorted(p.rsplit("/", 1)[-1] for p in st.glob(f"{layout.STATEMENT_CHECKS}/*/*.parquet"))


def test_recheck_reproduces_the_build_exactly(lake_copy):
    """Same rows in, same code, same checks out: row for row, including source and the numbers."""
    before = _all_checks(lake_copy)
    assert before, "the built lake should carry checks"
    counts = S.recheck(lake_copy)
    after = _all_checks(lake_copy)
    assert after == before
    assert counts["fsds_checks"] + counts["fallback_checks"] == len(before)
    assert counts["fsds_quarters"] > 0
    # written under the builders' own names, so a later quarter rebuild still supersedes them
    names = _check_files(lake_copy)
    assert names and all(n.startswith(("fsds_", "fallback_")) for n in names)


def test_recheck_recomputes_rather_than_copies(lake_copy, monkeypatch):
    """With the pass rule changed, every check comes out changed: the numbers were recomputed."""
    before = _all_checks(lake_copy)
    monkeypatch.setattr(chk, "_close", lambda lhs, rhs: False)
    monkeypatch.setattr(chk, "_eps_close", lambda lhs, rhs: False)
    S.recheck(lake_copy)
    after = _all_checks(lake_copy)
    assert len(after) == len(before)
    assert all(r[4] is False for r in after)
    # only the verdict moved; the operands are the build's
    assert [r[:4] + r[5:] for r in after] == [r[:4] + r[5:] for r in before]


def test_recheck_is_idempotent(lake_copy):
    S.recheck(lake_copy)
    once = _all_checks(lake_copy)
    S.recheck(lake_copy)
    assert _all_checks(lake_copy) == once
    assert len(_check_files(lake_copy)) == len(set(_check_files(lake_copy)))


def test_recheck_on_an_empty_lake_is_a_noop(tmp_path):
    assert S.recheck(Storage(str(tmp_path))) == {
        "fsds_quarters": 0,
        "fsds_checks": 0,
        "fallback_filings": 0,
        "fallback_checks": 0,
    }
