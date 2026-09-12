"""Phase 4 scheduler: run the daily refresh at a wall-clock time in a timezone, without GitHub Actions.

`filings-hub worker --at 06:00 --tz America/New_York` sleeps until the next run time, refreshes, repeats.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)


def next_run(now: datetime, at: str, tz: str, weekdays_only: bool = True) -> datetime:
    """Next `HH:MM` (in `tz`) strictly after `now` (aware). Weekends skipped when `weekdays_only`."""
    zone = ZoneInfo(tz)
    hh, mm = (int(x) for x in at.split(":"))
    local = now.astimezone(zone)
    candidate = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    while weekdays_only and candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def run_forever(
    job: Callable[[], object],
    at: str = "06:00",
    tz: str = "America/New_York",
    weekdays_only: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(ZoneInfo("UTC")),
    max_runs: int | None = None,
) -> int:
    """Loop: wait for the next slot, run `job`, log. Returns the number of runs (for tests / max_runs)."""
    runs = 0
    while max_runs is None or runs < max_runs:
        now = clock()
        target = next_run(now, at, tz, weekdays_only)
        wait = (target - now).total_seconds()
        log.info("worker: next refresh at %s (%s) in %.0f min", target.isoformat(), tz, wait / 60)
        if wait > 0:
            sleep(wait)
        try:
            job()
        except Exception:  # keep the loop alive; the job logs and alerts itself
            log.exception("worker: job failed")
        runs += 1
    return runs
