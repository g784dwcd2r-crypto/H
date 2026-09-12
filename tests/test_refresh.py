"""Daily refresh against a fake EDGAR: Apple files its FY2026 10-K."""

from __future__ import annotations

from datetime import date

import orjson
import pytest

from filings_hub.ingest import refresh as R
from filings_hub.lake import layout
from filings_hub.lake.duck import Duck
from filings_hub.lake.storage import Storage
from filings_hub.testing import edgar_fixtures as fx


class FakeEdgar:
    """Same surface as EdgarClient for everything the refresh touches."""

    def __init__(
        self,
        index_by_day: dict[date, list[tuple[int, str, str]]],
        fail_ciks: set[int] = frozenset(),
    ):
        self.index_by_day = index_by_day
        self.fail_ciks = fail_ciks
        self.calls: list[str] = []

    def fetch_daily_index(self, day: date) -> str | None:
        self.calls.append(f"index {day}")
        if day not in self.index_by_day:
            return None
        return fx.daily_index_text(day, self.index_by_day[day])

    def fetch_submissions(self, cik: int) -> dict:
        self.calls.append(f"submissions {cik}")
        if cik in self.fail_ciks:
            raise RuntimeError("boom")
        if cik == fx.APPLE:
            return fx.submissions_doc(cik, fx.APPLE_FILINGS + fx.APPLE_FY2026_FILINGS)
        return fx.submissions_doc(cik)

    def fetch_companyfacts(self, cik: int) -> dict | None:
        self.calls.append(f"facts {cik}")
        if cik == fx.APPLE:
            return fx.apple_companyfacts_with_fy2026()
        return fx.companyfacts_docs().get(cik)

    @staticmethod
    def fsds_url(quarter: str) -> str:
        return f"fake://fsds/{quarter}"

    def get_optional(self, url: str):
        self.calls.append(f"get {url}")
        return None  # no new FSDS quarter published


def _periods(storage: Storage, cik: int) -> dict[str, dict]:
    return {r["period_label"]: r for r in storage.read_parquet(layout.PERIODS).to_pylist() if r["cik"] == cik}


def test_refresh_new_10k(lake_copy: Storage, monkeypatch: pytest.MonkeyPatch):
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(R, "notify", lambda subject, body, **kw: alerts.append((subject, body)))
    today = date(2026, 11, 3)  # Tuesday
    monday = date(2026, 11, 2)
    fake = FakeEdgar({monday: [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026), (fx.JPM, "4", "0000019617-26-000050")]})

    run = R.run_refresh(lake_copy, fake, today=today, index_date=monday, load_db=False)
    assert run.status == "ok", run.summary()
    assert run.index_dates == ["2026-11-02"] and run.new_filings == 2 and run.ciks_refreshed == 1
    assert run.facts_rows > 0 and run.statements_built == 1 and run.error is None and run.failures == []
    # the Form 4 filer was not refreshed via the API (only results forms / 8-K trigger it) but the stub row exists
    assert "submissions 19617" not in fake.calls and "facts 320193" in fake.calls
    assert lake_copy.exists(layout.raw_daily_index(monday))
    assert lake_copy.exists(layout.raw_api_submissions(today, fx.APPLE)) and lake_copy.exists(
        layout.raw_api_companyfacts(today, fx.APPLE)
    )

    duck = Duck(lake_copy)
    duck.create_views()
    jpm = duck.fetch_dicts("SELECT source, form FROM filings WHERE accession = '0000019617-26-000050'")
    assert jpm == [{"source": "daily_index", "form": "4"}]
    apple_k = duck.fetch_dicts("SELECT source, report_date FROM filings WHERE accession = ?", [fx.APPLE_10K_FY2026])
    assert apple_k == [{"source": "submissions_api", "report_date": date(2026, 9, 26)}]

    p = _periods(lake_copy, fx.APPLE)
    assert p["FY2026"]["results_accession"] == fx.APPLE_10K_FY2026
    assert p["FY2026"]["earnings_release_accession"] == fx.APPLE_8K_FY2026  # came in through the API refresh
    stm = duck.fetch_dicts(
        "SELECT DISTINCT source, checks_passed FROM statements WHERE accession = ? AND statement = 'BS'",
        [fx.APPLE_10K_FY2026],
    )
    assert stm == [{"source": "facts_fallback", "checks_passed": True}]
    ni = duck.fetch_dicts(
        "SELECT value FROM statements WHERE accession = ? AND statement = 'IS' AND concept = 'NetIncomeLoss' AND is_primary_period",
        [fx.APPLE_10K_FY2026],
    )
    assert ni == [{"value": float(fx.APPLE_IS[fx.P_FY2026]["NetIncomeLoss"])}]
    logs = duck.fetch_dicts("SELECT kind, status, new_filings FROM run_log ORDER BY started_at")
    assert logs[-1] == {"kind": "refresh", "status": "ok", "new_filings": 2}
    duck.close()
    assert alerts == []

    # a second run over the same day is a no-op for filings and re-uses the raw index (idempotent)
    fake2 = FakeEdgar({monday: [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026)]})
    run2 = R.run_refresh(lake_copy, fake2, today=today, index_date=monday, load_db=False)
    assert run2.status == "ok" and "index 2026-11-02" not in fake2.calls


def test_refresh_catches_up_and_flags_empty_weekday(lake_copy: Storage, monkeypatch: pytest.MonkeyPatch):
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(R, "notify", lambda subject, body, **kw: alerts.append((subject, body)))
    fake = FakeEdgar({})
    # nothing indexed yet -> only yesterday; a Saturday with no index is not an "empty" run
    run = R.run_refresh(lake_copy, fake, today=date(2026, 9, 13), load_db=False)  # Sunday -> yesterday = Saturday
    assert run.status == "ok" and run.index_dates == [] and alerts == []
    # a weekday with an empty index is flagged
    fake = FakeEdgar({date(2026, 9, 14): []})
    run = R.run_refresh(lake_copy, fake, today=date(2026, 9, 15), load_db=False)
    assert run.status == "empty" and alerts and alerts[0][0].endswith("empty")
    # catch-up window: after 2026-09-14 was indexed, running on the 18th asks for 15..17
    assert R.index_dates_to_process(lake_copy, date(2026, 9, 18)) == [
        date(2026, 9, 15),
        date(2026, 9, 16),
        date(2026, 9, 17),
    ]
    assert R.index_dates_to_process(lake_copy, date(2026, 12, 1))[0] == date(2026, 11, 24)  # capped at 7 days
    assert R.index_dates_to_process(lake_copy, date(2026, 9, 18), date(2026, 9, 1)) == [date(2026, 9, 1)]


def test_refresh_isolated_company_failure(lake_copy: Storage, monkeypatch: pytest.MonkeyPatch):
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(R, "notify", lambda subject, body, **kw: alerts.append((subject, body)))
    day = date(2026, 11, 2)
    fake = FakeEdgar(
        {day: [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026), (fx.JPM, "8-K", "0000019617-26-000051")]},
        fail_ciks={fx.JPM},
    )
    run = R.run_refresh(lake_copy, fake, today=date(2026, 11, 3), index_date=day, load_db=False)
    assert run.status == "ok" and run.ciks_refreshed == 1 and len(run.failures) == 1 and "19617" in run.failures[0]
    assert _periods(lake_copy, fx.APPLE)["FY2026"]["results_accession"] == fx.APPLE_10K_FY2026


def test_refresh_total_failure_is_logged_and_alerted(lake_copy: Storage, monkeypatch: pytest.MonkeyPatch):
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(R, "notify", lambda subject, body, **kw: alerts.append((subject, body)))

    class Broken(FakeEdgar):
        def fetch_daily_index(self, day):
            raise RuntimeError("edgar down")

    run = R.run_refresh(lake_copy, Broken({}), today=date(2026, 11, 3), index_date=date(2026, 11, 2), load_db=False)
    assert run.status == "failed" and "edgar down" in run.error
    assert alerts[0][0] == "filings-hub refresh failed"
    duck = Duck(lake_copy)
    duck.create_views()
    assert duck.fetch_dicts("SELECT status FROM run_log ORDER BY started_at DESC LIMIT 1") == [{"status": "failed"}]
    duck.close()


def test_run_log_row_and_summary():
    run = R.RunLog(kind="backfill")
    run.finish("ok")
    row = run.row()
    assert row["kind"] == "backfill" and row["duration_seconds"] is not None and "backfill" in run.summary()
    assert orjson.dumps(row, default=str)


def test_new_fsds_quarter_is_picked_up(lake_copy: Storage):
    class WithFsds(FakeEdgar):
        def get_optional(self, url):
            if url.endswith("2026q2"):

                class R:  # minimal response
                    content = _q2_zip()

                return R()
            return None

    loaded = R.maybe_load_new_fsds(lake_copy, WithFsds({}), date(2026, 9, 11))
    assert loaded == ["2026q2"]
    assert not lake_copy.exists(f"{layout.statements_cik_dir(fx.APPLE)}/fallback_{fx.APPLE_10Q_Q2_2026}.parquet")


def _q2_zip() -> bytes:
    import io
    import zipfile

    q2 = {
        "sub": [
            fx._sub(
                fx.APPLE_10Q_Q2_2026,
                fx.APPLE,
                "10-Q",
                "2026-03-31",
                2026,
                "Q2",
                "2026-05-01",
                "0930",
            )
        ],
        "num": fx._apple_num(
            fx.APPLE_10Q_Q2_2026,
            [fx.P_Q2_2026, fx.P_H1_2026],
            ["2026-03-28", "2025-09-27"],
            [fx.P_H1_2026],
        ),
        "pre": fx._apple_pre(fx.APPLE_10Q_Q2_2026),
        "tag": fx._tags_for(fx.APPLE_PRE),
    }
    cols = {"sub": fx.SUB_COLS, "num": fx.NUM_COLS, "pre": fx.PRE_COLS, "tag": fx.TAG_COLS}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for t, lines in q2.items():
            zf.writestr(f"{t}.txt", "\t".join(cols[t]) + "\n" + "\n".join(lines) + "\n")
    return buf.getvalue()
