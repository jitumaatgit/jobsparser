---
status: accepted
date: 2026-10-08
---

# Replace the Google Sheets review pipeline with an in-repo review bench

The review pass — merging scrape output, removing false positives, tracking what had been
applied to — was owned by a Google Sheets workbook with an Apps Script merge, a
hand-maintained title-filter column, and a separate kanban.nvim board. That work now
lives in this repo as `jobsview review`, a Textual TUI over the CSVs the CLI already writes.

**Why.** The Sheets pipeline was the bottleneck after a scrape, not the scrape itself:
dedupe and filtering were manual, decisions did not persist (a rejected job surfaced
again the next day), and nothing recorded which search term produced a row — so the job
family, which `CONTEXT.md` already defined as the grouping for triage, could not be used
at all. Missing a job cannot be recovered, so the filter has to be fast and safe rather
than merely present.

**What changed in scope.** The scraper is otherwise untouched. Provenance stamping is the
only CLI change: `jobsparser` gains an optional `--term-label`, every row carries its
`term_label` plus the verbatim `search_term`, and `run_queries.sh` supplies the label by
parsing the `# --- Family ---` headers in `queries.txt`. Decisions and applications live
in a sidecar SQLite file (`data/review.db`) keyed on `job_url`; `data/jobs.db` stays a
derived, rebuildable index and holds nothing the user authored. Per-family *pattern*
exclusion rules are deliberately deferred to v2 — per-job memory (a false positive never
resurfaces) covers most of the value, and an auto-applied rule can drop jobs without a
human seeing them.

**Considered.** Writing survivors to Google Sheets via API instead — rejected, because it
keeps the dependency this work exists to shed and adds OAuth to a single-user tool.
Pattern exclusion rules in v1 — rejected for the reason above. A stdlib-only TUI —
rejected; list/detail panes and markdown description rendering are the substance of a
review bench, and the cost is one dependency. Storing decisions inside `jobs.db` —
rejected, because `jobsview ingest` unlinks that file on every run.

**Consequences.** This repo now owns triage and application tracking, which it previously
did not even in the weak sense of writing CSV; that rewrites the *Pipeline* and
*False positive* terms in `CONTEXT.md`. `jobsview.py` keeps its stdlib-only core —
`search`, `new` and `stats` stay install-free — while Textual is installed by a separate
`make bench-setup` target rather than by `make setup`. The kanban board is written, not
read: the `kanban.md` export overwrites the existing file, so the one hand-added card
still on it (`gardencenter`) must be re-entered in the bench before the first export.
Retiring `filter_job.py`, the pre-provenance CSVs under `~/notes/jobs/`, and the Sheets
workbook itself was explicitly left to the user.
