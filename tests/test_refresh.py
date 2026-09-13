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

    def get(self, url: str):
        import httpx

        from filings_hub.ingest.edgar_client import EdgarError

        self.calls.append(f"get {url}")
        resp = fx.edgar_document_handler(httpx.Request("GET", url))
        if resp.status_code >= 400:
            raise EdgarError(f"GET {url} -> HTTP {resp.status_code}")
        return resp


def _periods(storage: Storage, cik: int) -> dict[str, dict]:
    return {r["period_label"]: r for r in storage.read_parquet(layout.PERIODS).to_pylist() if r["cik"] == cik}


def test_refresh_new_10k(lake_copy: Storage, monkeypatch: pytest.MonkeyPatch):
    from filings_hub.ingest import alerts as A
    from filings_hub.ingest import digest as D

    alerts: list[tuple[str, str]] = []
    emails: list[tuple[str, str, str]] = []
    monkeypatch.setattr(R, "notify", lambda subject, body, **kw: alerts.append((subject, body)))
    monkeypatch.setattr(A, "send_email", lambda to, subject, body, **kw: emails.append((to, subject, body)) or True)
    D.save_subscription(lake_copy, "Analyst@Example.com", [fx.APPLE, fx.JPM])
    D.save_subscription(lake_copy, "other@example.com", [fx.RBC])
    today = date(2026, 11, 3)  # Tuesday
    monday = date(2026, 11, 2)
    fake = FakeEdgar({monday: [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026), (fx.JPM, "4", "0000019617-26-000050")]})

    run = R.run_refresh(lake_copy, fake, today=today, index_date=monday, load_db=False)
    assert run.status == "ok", run.summary()
    # the new filings' documents were fetched from their index pages and kept in the lake
    docs = lake_copy.read_parquet(f"{layout.documents_cik_dir(fx.APPLE)}/part-0.parquet").to_pylist()
    by_acc = {}
    for d in docs:
        by_acc.setdefault(d["accession"], set()).add(d["label"])
    assert "Annual report" in by_acc[fx.APPLE_10K_FY2026] and "Subsidiaries" in by_acc[fx.APPLE_10K_FY2026]
    assert "Earnings release" in by_acc[fx.APPLE_8K_FY2026]
    # one digest to the subscriber who follows Apple; the other follows a company that did not file
    assert run.emails_sent == 1 and [e[0] for e in emails] == ["analyst@example.com"]
    assert "Apple Inc." in emails[0][2] and "10-K" in emails[0][2]
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
    logs = duck.fetch_dicts("SELECT kind, status, new_filings FROM run_log WHERE run_id = ?", [run.run_id])
    assert logs == [{"kind": "refresh", "status": "ok", "new_filings": 2}]
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
    assert R.index_dates_to_process(lake_copy, date(2026, 12, 1)) == [date(2026, 9, d) for d in range(15, 22)]
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
    assert run.status == "failed" and run.ciks_refreshed == 1 and len(run.failures) == 1 and "19617" in run.failures[0]
    assert _periods(lake_copy, fx.APPLE)["FY2026"]["results_accession"] == fx.APPLE_10K_FY2026
    assert R.index_dates_to_process(lake_copy, date(2026, 12, 1))[0] == day
    assert alerts[0][0] == "filings-hub refresh failed"


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
    assert duck.fetch_dicts("SELECT status FROM run_log WHERE run_id = ?", [run.run_id]) == [{"status": "failed"}]
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


@pytest.mark.parametrize(
    "stage", ["stub", "facts", "documents", "periods", "statements", "metrics", "database", "digest"]
)
def test_failed_stages_retain_date_until_retry_finishes(lake_copy, monkeypatch, stage):
    """A raw download or an earlier stage's write must not acknowledge the remaining stages."""
    from filings_hub.db import load, run_log

    day, today = date(2026, 11, 2), date(2026, 11, 3)
    fake = FakeEdgar({day: [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026)]})
    monkeypatch.setattr(load, "load_incremental", lambda *a, **kw: None)
    monkeypatch.setattr(run_log, "publish_run_log", lambda *a, **kw: None)
    target, attribute = {
        "stub": (R.sync_filings, "upsert_filings"),
        "facts": (R.sync_facts, "refresh_cik_facts"),
        "documents": (R.documents, "ensure_documents"),
        "periods": (R, "rebuild_periods"),
        "statements": (R.sync_statements, "fill_fallbacks_for_cik"),
        "metrics": (R.metrics, "upsert_company_metrics"),
        "database": (load, "load_incremental"),
        "digest": (R.digest, "send_digests"),
    }[stage]
    original = getattr(target, attribute)

    def fail(*args, **kwargs):
        raise RuntimeError(f"injected {stage} failure")

    monkeypatch.setattr(target, attribute, fail)
    first = R.run_refresh(lake_copy, fake, today=today, database_url="postgresql://unused", alert=False)
    assert first.status == "failed", first.summary()
    assert lake_copy.exists(layout.raw_daily_index(day))
    assert R.last_indexed_date(lake_copy) is None
    # The failed date survives even when it is much older than the ordinary catch-up window.
    assert day in R.index_dates_to_process(lake_copy, date(2026, 12, 1))
    monkeypatch.setattr(target, attribute, original)
    retried = FakeEdgar({})
    second = R.run_refresh(lake_copy, retried, today=today, database_url="postgresql://unused", alert=False)
    assert second.status == "ok", second.summary()
    assert second.db_loaded and second.ciks_refreshed == 1
    assert "index 2026-11-02" not in retried.calls
    assert R.index_dates_to_process(lake_copy, today) == []
    assert _periods(lake_copy, fx.APPLE)["FY2026"]["results_accession"] == fx.APPLE_10K_FY2026


def test_failed_download_and_legacy_raw_index_are_retried(tmp_path, monkeypatch):
    storage = Storage(str(tmp_path))
    day = date(2026, 11, 2)

    class Broken(FakeEdgar):
        def fetch_daily_index(self, day):
            raise RuntimeError("temporary outage")

    first = R.run_refresh(storage, Broken({}), today=date(2026, 11, 3), load_db=False, alert=False)
    assert first.status == "failed" and not storage.exists(layout.raw_daily_index(day))
    assert day in R.index_dates_to_process(storage, date(2026, 12, 1))
    # Upgrade recovery: cached raw indices without a durable completion marker remain work.
    legacy_day = date(2026, 10, 1)
    storage.write_text(layout.raw_daily_index(legacy_day), fx.daily_index_text(legacy_day, []))
    assert legacy_day in R.index_dates_to_process(storage, date(2026, 12, 1))


def test_legacy_raw_recovery_does_not_resend_old_digests(lake_copy, monkeypatch):
    day = date(2026, 11, 2)
    lake_copy.write_text(
        layout.raw_daily_index(day), fx.daily_index_text(day, [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026)])
    )
    sent = []
    monkeypatch.setattr(R.digest, "send_digests", lambda *args, **kwargs: sent.append(args) or 1)
    recovered = R.run_refresh(lake_copy, FakeEdgar({}), today=date(2026, 11, 3), load_db=False, alert=False)
    assert recovered.status == "ok" and recovered.ciks_refreshed == 1
    assert not sent and recovered.emails_sent == 0


def test_missing_weekday_index_retries_after_newer_date_succeeds(lake_copy):
    monday, tuesday = date(2026, 11, 2), date(2026, 11, 3)
    first = R.run_refresh(lake_copy, FakeEdgar({}), today=tuesday, load_db=False, alert=False)
    assert first.status == "empty"
    assert R.last_indexed_date(lake_copy) is None
    second = R.run_refresh(
        lake_copy,
        FakeEdgar({tuesday: []}),
        today=date(2026, 11, 4),
        load_db=False,
        alert=False,
    )
    assert second.status == "empty" and R.last_indexed_date(lake_copy) == tuesday
    assert monday in R.index_dates_to_process(lake_copy, date(2026, 12, 1))
    published = FakeEdgar({monday: [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026)]})
    recovered = R.run_refresh(lake_copy, published, today=date(2026, 11, 4), load_db=False, alert=False)
    assert recovered.status == "ok" and recovered.ciks_refreshed == 1
    assert R.index_dates_to_process(lake_copy, date(2026, 11, 4)) == []


def test_long_outage_backlog_is_batched_without_losing_dates(lake_copy):
    first = R.run_refresh(
        lake_copy, FakeEdgar({date(2026, 11, 2): []}), today=date(2026, 11, 3), load_db=False, alert=False
    )
    assert first.status == "empty"
    today = date(2026, 11, 20)
    seen = []
    available = {date(2026, 11, d): [] for d in range(3, 20)}
    while dates := R.index_dates_to_process(lake_copy, today):
        assert len(dates) <= R.MAX_CATCHUP_DAYS
        seen.extend(dates)
        run = R.run_refresh(lake_copy, FakeEdgar(available), today=today, load_db=False, alert=False)
        assert run.status in ("ok", "empty")
    assert seen == [date(2026, 11, d) for d in range(3, 20)]


def test_explicit_since_persists_remaining_backlog_and_rotates_holiday_retries(lake_copy):
    today = date(2026, 11, 20)
    R.run_refresh(lake_copy, FakeEdgar({}), today=today, since=date(2026, 11, 2), load_db=False, alert=False)
    next_dates = R.index_dates_to_process(lake_copy, today)
    assert len(next_dates) <= R.MAX_CATCHUP_DAYS
    assert any(day >= date(2026, 11, 9) for day in next_dates)
    assert R._catchup_start(lake_copy, today) == date(2026, 11, 2)


@pytest.mark.parametrize("failure", ["no_facts", "builder_error"])
def test_failed_fallback_rebuild_retains_previous_served_bytes(lake_copy, monkeypatch, failure):
    day, today = date(2026, 11, 2), date(2026, 11, 3)
    run = R.run_refresh(
        lake_copy, FakeEdgar({day: [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026)]}), today=today, load_db=False, alert=False
    )
    assert run.status == "ok"
    statement = f"{layout.statements_cik_dir(fx.APPLE)}/fallback_{fx.APPLE_10K_FY2026}.parquet"
    checks = f"{layout.statement_checks_cik_dir(fx.APPLE)}/fallback_{fx.APPLE_10K_FY2026}.parquet"
    before = {rel: lake_copy.read_bytes(rel) for rel in (statement, checks)}

    def fail(*args, **kwargs):
        raise RuntimeError("injected builder failure")

    if failure == "no_facts":
        monkeypatch.setattr(R.sync_statements, "_facts_for", lambda *args: [])
        assert (
            R.sync_statements.fill_fallbacks_for_cik(lake_copy, fx.APPLE, rebuild_accessions={fx.APPLE_10K_FY2026}) == 0
        )
    else:
        monkeypatch.setattr(R.sync_statements, "build_fallback_rows", fail)
        with pytest.raises(RuntimeError):
            R.sync_statements.fill_fallbacks_for_cik(lake_copy, fx.APPLE, rebuild_accessions={fx.APPLE_10K_FY2026})
    assert before == {rel: lake_copy.read_bytes(rel) for rel in before}


def test_retry_repairs_fallback_written_without_checks(lake_copy, monkeypatch):
    """Failure after the statement file is published must still rebuild its missing checks."""
    day, today = date(2026, 11, 2), date(2026, 11, 3)
    original = lake_copy.write_parquet
    expected = f"{layout.statement_checks_cik_dir(fx.APPLE)}/fallback_{fx.APPLE_10K_FY2026}.parquet"
    fsds_before = {p: lake_copy.read_bytes(p) for p in lake_copy.glob(f"{layout.STATEMENTS}/*/fsds_*.parquet")}

    def fail_checks(rel, table, **kwargs):
        if rel == expected:
            raise RuntimeError("crash between statement and check publication")
        original(rel, table, **kwargs)

    monkeypatch.setattr(lake_copy, "write_parquet", fail_checks)
    first = R.run_refresh(
        lake_copy,
        FakeEdgar({day: [(fx.APPLE, "10-K", fx.APPLE_10K_FY2026)]}),
        today=today,
        load_db=False,
        alert=False,
    )
    assert first.status == "failed"
    assert lake_copy.exists(f"{layout.statements_cik_dir(fx.APPLE)}/fallback_{fx.APPLE_10K_FY2026}.parquet")
    assert not lake_copy.exists(expected)
    monkeypatch.setattr(lake_copy, "write_parquet", original)
    retry = R.run_refresh(lake_copy, FakeEdgar({}), today=today, load_db=False, alert=False)
    assert retry.status == "ok", retry.summary()
    assert lake_copy.exists(expected) and lake_copy.read_parquet(expected).num_rows > 0
    assert fsds_before == {p: lake_copy.read_bytes(p) for p in fsds_before}


@pytest.mark.parametrize("stage", ["download", "load", "build"])
def test_fsds_cached_partial_work_is_rebuilt(lake_copy, monkeypatch, stage):
    quarter = "2026q2"
    calls = []
    monkeypatch.setattr(R.bulk, "fsds_quarters", lambda today: [quarter])

    def download(storage, client, quarters):
        calls.append(("download", quarters))
        storage.write_bytes(layout.raw_fsds_zip(quarter), b"cached zip")
        if stage == "download" and len(calls) == 1:
            raise RuntimeError("crash after download")
        return quarters

    def load(storage, quarters, force=False):
        calls.append(("load", force))
        if stage == "load" and sum(c[0] == "load" for c in calls) == 1:
            raise RuntimeError("crash during load")
        return quarters

    def build(storage, quarters, force=False):
        calls.append(("build", force))
        if stage == "build" and sum(c[0] == "build" for c in calls) == 1:
            raise RuntimeError("crash during build")
        return quarters

    monkeypatch.setattr(R.bulk, "download_fsds", download)
    monkeypatch.setattr(R.fsds, "load_all_fsds", load)
    monkeypatch.setattr(R.sync_statements, "build_all_fsds", build)
    with pytest.raises(RuntimeError):
        R.maybe_load_new_fsds(lake_copy, FakeEdgar({}), date(2026, 9, 11))
    assert R.maybe_load_new_fsds(lake_copy, FakeEdgar({}), date(2026, 9, 11)) == [quarter]
    assert calls[-2:] == [("load", True), ("build", True)]


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
