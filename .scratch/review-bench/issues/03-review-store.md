Status: resolved
Type: task

# 03 — Sidecar store for decisions and applications

`data/review.db` is created as a SQLite sidecar keyed on `job_url`, holding the review
decision, the application status and the run numbers a row was seen in. It is the only
source of truth for user-authored state, so it must never be rebuilt or unlinked.

## Change

`jobsview.py`:

- `REVIEW_DDL` — a table with `job_url TEXT PRIMARY KEY`, `decision TEXT NOT NULL DEFAULT
  'unreviewed'`, `application_status TEXT NOT NULL DEFAULT 'none'`, `first_run INTEGER`,
  `last_run INTEGER`, `decided_at TEXT`, `updated_at TEXT`. Use the same
  `first_run`/`last_run` names as `jobs.db` so the join reads naturally.
- A `_review_db(args)` opener that creates the file and applies the DDL when missing.
  Creating it is safe on a read path; deleting it is never.
- Row helpers that validate against the state sets in the spec and raise `ValueError` with
  the offending value on a bad one — the two axes' vocabularies must not be conflated, so
  `false_positive` is not a valid application status and `rejected` is not a valid review
  decision.
- `jobsview review --list` prints the store so state can be inspected without the TUI;
  used by the tests and handy for debugging.
- An index is not needed at this size — skip it.

Deliberately no schema migration machinery: hand-edit or re-derive if the columns change.
Say so in a comment.

## Acceptance

- Opening a missing `data/review.db` creates it with the exact columns above and an empty
  table; the file is left in place by every subsequent read.
- Writing `decision='keep'` then re-opening the file returns `keep` across separate
  processes.
- `set decision='rejected'` raises `ValueError` mentioning `rejected`; `set
  application_status='false_positive'` likewise.
- Defaults are `unreviewed` and `none` for a newly inserted URL.
- `jobsview review --list` on a DB with two rows prints both, one per line.

## Blocked by

Nothing.

## Comments

**2026-10-08.** Implemented in `jobsview.py` as a section after `cmd_ingest`: `REVIEW_DDL`
(with `CREATE TABLE IF NOT EXISTS`, so opening is idempotent and there is deliberately no
migration machinery), `DECISIONS`/`APPLICATION_STATUSES` as the single definition of each
vocabulary, `_utcnow`/`_check_axis`, the `_review_db(args)` opener, three row helpers
(`ensure_review_row`, `set_decision`, `set_application_status`) and `jobsview review --list`.

Two decisions worth recording:

- The sidecar lives at `<data-dir>/review.db`, not at `--db`. `--db` names the derived jobs
  index that `ingest` unlinks and rebuilds on every run; the review store belongs to the
  dataset and must outlive that, so keying it off `--data-dir` keeps it outside the derived
  path's blast radius.
- `decided_at` is the timestamp of the decision the row currently carries: unchanged while
  the verdict moves between two decided values, cleared when it goes back to `unreviewed`,
  which is the absence of a decision. Only `updated_at` moves on a later change.

No CLI write surface on purpose: the review bench (ticket 05) is where decisions are made,
and `--list` is the headless inspection hook the tests and debugging use.

Verified: `jobsparser/tests/test_review_store.py` (12 tests — one per acceptance line, plus
the `ON CONFLICT` branch and the timestamp semantics) — 24/24 on the full suite. Smoke run
against the real default path: `jobsview review --list` with no store creates
`data/review.db` and prints `(review store is empty)`; a write in one interpreter is visible
in the next; both cross-axis values (`rejected` as a review decision, `false_positive` as an
application status) raise `ValueError` naming the offending value; and a read leaves the
stored rows untouched.

**Review follow-up (same day).** Both axes re-ran the ticket independently; all five
acceptance lines pass and no conflation between the axes is reachable. Six findings were
real enough to fix in the same commit:

- The test module imported `jobsview` without putting the repo root on `sys.path`, so it
  only ran from the repo root — now shimmed like its siblings and verified from `/tmp`.
- `ensure_review_row`'s `ON CONFLICT` branch — the "an ingest can never destroy a
  decision" invariant — had no test. Now covered: run numbers only ever widen, and a prior
  decision, application status and `decided_at` survive.
- `decided_at` survived a revert to `unreviewed`, so the timestamp of a mis-keyed decision
  would be inherited by the later `keep`. It now clears when the row stops being decided,
  which is what ticket 05's undo needs.
- An unopenable store produced a traceback instead of the file's usual one-line error.
- `updated_at` moved on every ingest pass even when nothing changed; it now only moves when
  the run range does, per spec line 81.
- The DDL is effectively write-once, so both vocabularies now carry `CHECK` constraints —
  the storage layer is the one place the two axes can be held apart permanently.

Known edges left as-is, recorded for the tickets that will meet them: a direct-SQL repair
write is now blocked by those `CHECK`s (that is the point); `job_url` permits NULL because
the DDL is verbatim from the ticket, and the ingest loop must keep skipping rows with no
URL as `cmd_ingest` already does; and there is still no CLI write surface, since the review
bench (ticket 05) is where decisions are made.
