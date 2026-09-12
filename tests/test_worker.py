from datetime import datetime
from zoneinfo import ZoneInfo

from filings_hub.ingest.worker import next_run, run_forever

NY = ZoneInfo("America/New_York")


def test_next_run_same_day_and_rollover():
    now = datetime(2026, 9, 14, 5, 30, tzinfo=NY)  # Monday 05:30
    assert next_run(now, "06:00", "America/New_York") == datetime(2026, 9, 14, 6, 0, tzinfo=NY)
    now = datetime(2026, 9, 14, 6, 0, tzinfo=NY)
    assert next_run(now, "06:00", "America/New_York") == datetime(2026, 9, 15, 6, 0, tzinfo=NY)


def test_next_run_skips_weekend_and_handles_utc_input():
    fri = datetime(2026, 9, 18, 12, 0, tzinfo=ZoneInfo("UTC"))  # Friday 08:00 NY
    assert next_run(fri, "06:00", "America/New_York") == datetime(2026, 9, 21, 6, 0, tzinfo=NY)  # Monday
    assert next_run(fri, "06:00", "America/New_York", weekdays_only=False) == datetime(2026, 9, 19, 6, 0, tzinfo=NY)


def test_run_forever_runs_job_and_survives_failures():
    calls: list[str] = []
    slept: list[float] = []
    ticks = iter([datetime(2026, 9, 14, 5, 0, tzinfo=NY), datetime(2026, 9, 14, 6, 0, tzinfo=NY)])

    def job() -> None:
        calls.append("x")
        if len(calls) == 1:
            raise RuntimeError("first run fails")

    n = run_forever(job, at="06:00", tz="America/New_York", sleep=slept.append, clock=lambda: next(ticks), max_runs=2)
    assert n == 2 and calls == ["x", "x"]
    assert slept[0] == 3600 and slept[1] == 24 * 3600
