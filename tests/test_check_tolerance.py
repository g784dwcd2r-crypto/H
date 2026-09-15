"""Step 1: the flat-tolerance measurement. Controlled rows with known gaps, then a real-lake smoke."""

import pyarrow as pa

from filings_hub.ingest import check_tolerance as ct
from filings_hub.ingest.sync_statements import CHECKS_SCHEMA
from filings_hub.lake import layout
from filings_hub.lake.storage import Storage

# Each row: (check_name, lhs, rhs, passed). difference is lhs - rhs. Gaps are chosen so each lands in
# a known band. Standard tolerance is 0.5 %, so q = (gap / max|side|) / 0.005; EPS uses 1 %.
ROWS = [
    ("assets_eq_liabilities_and_equity", 1_000_000, 1_000_000, True),  # gap 0        -> exact
    ("assets_eq_liabilities_and_equity", 1_000_000, 1_000_010, True),  # q ~ 0.002    -> <0.2
    ("assets_eq_liabilities_and_equity", 1_000_000, 1_002_000, True),  # q ~ 0.40     -> 0.2-0.6
    ("assets_eq_liabilities_and_equity", 1_000_000, 1_003_500, True),  # q ~ 0.70     -> 0.6-0.8
    ("assets_eq_liabilities_and_equity", 1_000_000, 1_004_500, True),  # q ~ 0.90     -> near-miss
    ("assets_eq_liabilities_and_equity", 100, 100.5, True),  # small numbers -> floor
    ("assets_eq_liabilities_and_equity", 1_000_000, 1_007_000, False),  # q ~ 1.39     -> just-over
    ("assets_eq_liabilities_and_equity", 1_000_000, 1_500_000, False),  # q ~ 66       -> >10x
    ("eps_basic", 2.00, 2.018, True),  # q ~ 0.89     -> near-miss (eps)
]


def _seed(storage: Storage) -> None:
    rows = []
    for i, (name, lhs, rhs, passed) in enumerate(ROWS):
        rows.append(
            {
                "accession": f"acc-{i}",
                "cik": 42,
                "statement": "IS" if name.startswith("eps") else "BS",
                "check_name": name,
                "passed": passed,
                "lhs": float(lhs),
                "rhs": float(rhs),
                "difference": float(lhs) - float(rhs),
                "detail": "",
                "source": "fsds",
            }
        )
    table = pa.Table.from_pylist(rows, schema=CHECKS_SCHEMA)
    storage.write_parquet(f"{layout.statement_checks_cik_dir(42)}/checks.parquet", table)


def test_bands_land_where_expected(tmp_path):
    st = Storage(str(tmp_path))
    _seed(st)
    rep = ct.tolerance_report(st)

    assert rep["total"] == len(ROWS)

    std = rep["standard"]
    assert std["pass_bands"] == {
        "exact": 1,
        "<0.2": 1,
        "0.2-0.6": 1,
        "0.6-0.8": 1,
        "near-miss": 1,
    }
    assert std["governed_passes"] == 5
    assert std["floor_passes"] == 1
    assert std["passes"] == 6  # 5 governed + 1 floor
    assert std["near_miss"] == 1
    assert std["near_miss_share"] == 1 / 5
    assert std["fail_bands"] == {"just-over": 1, "2-10x": 0, ">10x": 1}
    assert std["fails"] == 2

    eps = rep["eps"]
    assert eps["near_miss"] == 1
    assert eps["governed_passes"] == 1
    assert eps["fails"] == 0


def test_verdict_warns_when_near_misses_are_common(tmp_path):
    st = Storage(str(tmp_path))
    _seed(st)
    rep = ct.tolerance_report(st)
    # 1 of 5 governed passes is a near miss (20 %), well over the 1 % line -> the warning verdict.
    assert "likely hiding real breaks" in rep["verdict"]


def test_empty_lake_says_so(tmp_path):
    rep = ct.tolerance_report(Storage(str(tmp_path)))
    assert rep["total"] == 0
    assert "no statement_checks" in rep["message"]


def test_format_report_is_readable(tmp_path):
    st = Storage(str(tmp_path))
    _seed(st)
    text = ct.format_report(ct.tolerance_report(st))
    assert "Checks measured: 9" in text
    assert "near miss" in text
    assert "tolerance 0.5 %" in text and "tolerance 1 %" in text


def test_runs_on_the_real_built_lake(built_lake):
    """It runs on genuine pipeline output (synthetic companies, real check logic) and totals up."""
    rep = ct.tolerance_report(built_lake)
    assert rep["total"] > 0
    assert rep["standard"]["passes"] + rep["standard"]["fails"] <= rep["total"]
    assert isinstance(rep["verdict"], str) and rep["verdict"]


def test_the_approximate_eps_checks_are_not_measured(tmp_path):
    """The 5 % on an inferred numerator is a design choice, not a tolerance to measure."""
    st = Storage(str(tmp_path))
    _seed(st)
    before = ct.tolerance_report(st)
    st.write_parquet(
        f"{layout.statement_checks_cik_dir(77)}/approx.parquet",
        pa.Table.from_pylist(
            [
                {
                    "accession": "x1",
                    "cik": 77,
                    "statement": "IS",
                    "check_name": "eps_basic_approx",
                    "passed": False,
                    "lhs": 1.0,
                    "rhs": 1.08,
                    "difference": -0.08,
                    "detail": "",
                    "source": "fsds",
                }
            ],
            schema=CHECKS_SCHEMA,
        ),
    )
    assert ct.tolerance_report(st) == before
