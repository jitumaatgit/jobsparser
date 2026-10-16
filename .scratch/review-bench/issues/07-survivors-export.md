Status: ready-for-agent
Type: task

# 07 — Survivors CSV export

`jobsview export` writes `data/survivors.csv` — a full snapshot of every kept row in the
shape the resume synthesis step already reads. This replaces
`~/notes/scripts/filter_job.py` and its `interesting-jobs.csv` output.

## Change

`jobsview.py`:

- New `export` subcommand, `--output` (default `data/survivors.csv`). It runs entirely
  headless — no Textual import.
- Columns, in this order: `job_url_direct`, `title`, `company`, `date_posted`,
  `min_amount`, `max_amount`, `description`, `search_term`, `term_label`,
  `job_family_source`, `decision`, `application_status`. The first seven are exactly
  `filter_job.py`'s output in the same order, so downstream prompts and scripts keep
  working unchanged. `job_family_source` sits directly after the provenance columns it
  qualifies (`stamped` / `inferred` / `unknown`), so a guessed family is never mistaken
  for a recorded one.
- Query the union of `jobs.db` and `review.db` on `job_url`, filtered to
  `decision = 'keep'`, ordered by `date_posted DESC`.
- Create the parent directory if missing, overwrite the file on every run, and print the
  count written. An empty result writes a header-only file rather than deleting or
  skipping — the file must never lie.
- `jobsview review` gets an `x` key that shells out to this same export and shows the
  count, so the TUI and CLI share one code path.

## Acceptance

- With 2 kept and 3 false-positive rows in a fixture, `jobsview export` writes 2 rows and
  a header of exactly the 12 columns named above, the first seven matching
  `filter_job.py`'s names and order, with `job_family_source` correct for a stamped and
  an inferred row.
- Re-running the export after a rejection is written drops that row from the file and
  rewrites it (no append, no stale rows).
- An all-rejected fixture produces a header-only CSV, not a missing file.
- `data/survivors.csv`'s first seven column names equal those in the current
  `~/notes/.../interesting-jobs.csv`.
- `x` in the TUI produces a byte-identical file to the CLI export for the same state.
- No Textual import is needed for `jobsview export`.

## Blocked by

[05](05-bench-tui.md)
