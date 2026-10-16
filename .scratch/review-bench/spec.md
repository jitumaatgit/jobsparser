# Review bench

Spec for the in-repo review bench that replaces the Google Sheets review pass. Every
decision here was settled in a design interview on 2026-10-08 — reasoning and rejected
alternatives live in `docs/adr/0002-replace-sheets-review-pipeline.md`, and the vocabulary
in `CONTEXT.md` is binding on this spec.

## Goal

The scraper already runs unattended for about an hour. The bottleneck is what happens
after: results had to be merged, deduped and hand-filtered in a Google Sheets workbook
whose decisions survived only as long as a human kept a filter column tidy. The review
bench is where that pass now happens — fast enough to work through hundreds of false
positives, and safe enough that a good job cannot silently fall through.

## Non-goals

- **Triggering or watching a scrape.** The CLI keeps running standalone; the bench reads
  the CSVs it already writes.
- **Per-family pattern exclusion rules** (the Sheets columns A–D equivalent). Deferred to
  v2 — per-job memory covers most of the value, and an auto-applied rule can drop jobs
  without a human seeing them.
- **Writing resumes or application content.**
- **Writing to Google Sheets.**

## Shape

```
data/jobs_*.csv ──jobsview ingest──▶ data/jobs.db    derived index; unlinked and rebuilt
                                                   │   by every ingest
                                                   ├── join on job_url ─▶ data/review.db
                                                   │        ▲             sidecar; source
                                                   │        └── read/write │ of truth for
                                                   │                       decisions +
                                                   │                       applications
                                                   │
                                                   └── data/survivors.csv   full snapshot
                                                       ~/notes/.../kanban.md one-way export
```

The scraper is otherwise untouched; provenance stamping below is the only CLI change.

## Provenance

`jobsparser` gains an **optional** `--term-label`. `run_queries.sh` parses each
`# --- Family ---` header in `queries.txt` and passes it as `--term-label` for the term
that follows, so `queries.txt` stays the single file that is edited and the label *is* the
job family. No second mapping layer.

Each CSV gains two columns:

| Column        | Value                                                        |
| ------------- | ------------------------------------------------------------ |
| `search_term` | the verbatim `--search-term` string                          |
| `term_label`  | the label passed via `--term-label`; empty when none was given |

Rows scraped before these columns existed (the 302 rows now in `data/jobs_0.csv` and
`data/jobs_1.csv`) get a family guessed by matching their title against the terms in
`queries.txt`. The guess is marked: `job_family_source` is `stamped` (from the CSV),
`inferred` (backfilled) or `unknown`. **An inferred family is display-only and must never
be the basis of an exclusion rule.** That guard matters when v2 pattern rules land; it
exists now because the backfill is a guess.

## Data

**`data/jobs.db`** stays exactly as it is: a derived index, unlinked and rebuilt by
`jobsview ingest`, still the FTS5 and salary-derivation home. Nothing user-authored may
live in it.

**`data/review.db`** is new, and is the only source of truth for decisions and
applications:

| Column             | Values                                                            |
| ------------------ | ----------------------------------------------------------------- |
| `job_url`          | primary key; matches `jobsview`'s existing dedup key               |
| `decision`         | `unreviewed` \| `keep` \| `false_positive`                          |
| `application_status`| `none` \| `applied` \| `interview` \| `offer` \| `rejected` \| `withdrawn` |
| `first_run`        | run number the row was first seen (same names as `jobs.db`)        |
| `last_run`         | run number the row was last seen; drives staleness display         |
| `decided_at`       | timestamp of the first decision                                    |
| `updated_at`       | timestamp of the last change                                       |

A row in `review.db` that stops appearing in newer CSVs keeps its state; the bench shows
`last_run` and rows are never dropped.

**Auto-ingest.** `jobsview review` compares `data/jobs.db`'s mtime against the newest
`data/jobs_*.csv` and ingests first when the CSVs are newer. Decisions live in the
sidecar, so an ingest can never destroy them.

## The two axes

**Review decision** — `unreviewed` · `keep` (= a **survivor**) · `false_positive`
**Application status** — `none` · `applied` · `interview` · `offer` · `rejected` (the
employer declined) · `withdrawn`

They are orthogonal, and the two rejections are different concepts: `false_positive` means
the row was never worth applying to, `rejected` means an employer declined. `CONTEXT.md`
carries that distinction and the code must keep the names apart.

## Interaction

- **Flat queue** defaulting to unreviewed rows, with a family filter to narrow. The job
  family is a grouping, not a mandatory unit of work.
- **Auto-advance**: after any action the cursor jumps to the next unreviewed row.
- **Filters**: search over title/company, plus family and decision-state filters.
- **Undo**: `Ctrl-Z` walks back the last action, and a recent-decisions list shows where
  you are. A mis-keyed `false_positive` must not be permanent — a missed job cannot be
  recovered either way.
- **Detail pane** renders the description as markdown (rich).
- **`v`** opens `job_url_direct`, falling back to `job_url` when the direct link is empty.
- **Bindings** from the original sketch — `j/k`, `enter` detail, `v` browser, `space` for
  the review decision — plus one key per application status and arrow keys throughout.

Exports are CLI subcommands (`jobsview export`, `jobsview kanban`) that run headless, with
keys in the TUI as shortcuts. That keeps them scriptable and testable without a terminal.

## Outputs

### `data/survivors.csv`

A full snapshot of every kept row, overwritten on each export, `--output` to override.
Columns, in this order: `job_url_direct`, `title`, `company`, `date_posted`,
`min_amount`, `max_amount`, `description` — the 7 that `filter_job.py` already produced, so
the resume synthesis step downstream keeps its shape — then `search_term`, `term_label`,
`job_family_source`, `decision`, `application_status`. `job_family_source` follows the
provenance columns it qualifies, so a guessed family is never mistaken for a recorded one.
A full snapshot rather than a delta keeps the file deterministic and rebuildable; the
downstream resume step filters to `decision=keep AND application=none` when it wants only
the queue of unapplied survivors.

### `kanban.md`

Written to the existing
`~/notes/docs/90-archives/04-finding-employment-project/application-process/kanban.md`,
so the kanban.nvim board keeps working as a viewer. `--kanban` to override. The export is
**one-way and overwrites the file**; hand edits to the board are lost by design.

Status-to-column mapping:

| Application status | Board section    |
| ------------------ | ---------------- |
| `none`             | `## Interested`  |
| `applied`          | `## Applied`     |
| `interview`        | `## Interview`   |
| `offer`            | `## Offer`       |
| `rejected`         | `## Rejection`   |
| `withdrawn`        | `## Withdrawn`   (new section) |

Only kept rows appear on the board; false positives do not.

## Verification

1. Headless Textual `run_test()` pilot — behaviour: no crash, the queue advances, undo
   restores, filters narrow, exports write the right files.
2. **Your terminal, on the first screen, before anything is built on top of it.** Agent
   sessions here have been `TERM=dumb`, so rendering cannot be confirmed from one. About
   five minutes, once, before ticket 06 starts.

## Migration gate

Before the **first** `kanban.md` export (ticket 08), the board's hand-added cards must be
re-entered in the bench. Today that is exactly one: `gardencenter` under `## Applied`. The
export overwrites the file — a deliberate choice, not an oversight.

## Deferred to v2

- Per-family pattern exclusion rules (title/company/location patterns) applied on load,
  with the guard that an inferred family never drives one.
- Retiring `filter_job.py`, the CSVs under `~/notes/jobs/`, and the Google Sheets
  workbook. **Not** part of this feature; deleting them is the user's call.

## Tickets

`issues/`, numbered from `01`. `01`–`04` are the data layer with no UI dependency;
`05`–`06` the TUI; `07`–`08` the exports; `09` the human terminal check; `10` docs.
