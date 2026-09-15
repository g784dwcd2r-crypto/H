# Reports shared with reviewers

Snapshots, not live data. Each file is what the checks said on the day in its name, kept so a
reviewer can be sent a link rather than asked to run a command.

Regenerate with:

```
LAKE_ROOT=data filings-hub check-report --xlsx reports/failures-YYYY-MM-DD.xlsx
```

**Date every file.** These are a few megabytes each and every version is kept in the repository's
history forever, so overwriting one in place buries the old numbers and adds a second full copy
regardless. A dated name makes it obvious which run a reader is looking at, and lets an old one be
deleted once nobody needs it.

## What is in `failures-*.xlsx`

Every arithmetic check that failed, one row each.

* **Summary** — the headline, the split by check, the split by reason.
* **Failures** — company, filing, which check, why, the two numbers compared.

Filter the **Why** column first. `unexplained` is the part that is still ours to fix and the only
count that should be shrinking. A share count filed in thousands, an inverted sign, or a side tagged
as zero is the filer's own tagging error: it is listed, never silently corrected.
