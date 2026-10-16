Status: resolved
Type: task

# 04 — Join the family map, backfill legacy rows, auto-ingest

Four pieces that make the queue real: the family comes from `queries.txt`, the 302 legacy
rows get a clearly-marked guess, `jobsview review` ingests on its own when the CSVs are
newer, and the two databases are joined.

## Change

`jobsview.py`:

1. **Family map.** Parse `queries.txt` into `{raw_search_term: family}` using the same
   `# --- <Family> ---` header rule as ticket 02. Accept `--queries` (default
   `queries.txt`). A term absent from the map yields family `(unknown)`.
2. **Backfill.** For a row whose `term_label` is empty (the 302 legacy rows), guess a
   family by matching the title against the terms in the map and set `job_family_source`
   to `inferred`. `stamped` when the CSV carried the label, `unknown` when neither. The
   guess is display-only — nothing may use `inferred` to exclude a row, and that must be
   enforced or commented at every future call site.
3. **Auto-ingest.** `jobsview review` compares `data/jobs.db`'s mtime with the newest
   `data/jobs_*.csv` and runs the existing ingest when the CSVs are newer. Missing DB with
   CSVs present → ingest. Missing both → exit with the current "run ingest" message.
4. **The join.** `jobsview review --list` shows one row per job: title, company, location,
   date, pay, family (with `inferred` flagged), decision, application status, `last_run`.
   A row absent from `review.db` is `unreviewed`/`none` by default.

Keep the matching in one function with a test-sized footprint — it is a guess and will
need to be re-tuned, so it must be cheap to change.

## Acceptance

- A CSV with `term_label` set yields family `stamped` from that label, not from the map.
- A legacy row (no `term_label`) yields `inferred`, and the family shown comes from a title
  match.
- A row matching no term and `term_label` missing yields `unknown`.
- Touching a CSV then running `jobsview review --list` re-ingests without being asked;
  running it twice does not re-ingest.
- With no `data/jobs.db` and no CSVs, `jobsview review` exits non-zero with the existing
  "run: python3 jobsview.py ingest" message.
- No code path excludes a row because its family was inferred.

## Blocked by

[01](01-cli-provenance.md), [02](02-run-queries-labels.md), [03](03-review-store.md)

## Comments

**2026-10-08.** All six acceptance lines verified on the real `data/` directory (the 302
legacy rows) and in `jobsparser/tests/test_ingest_families.py` (22 tests) — 46/46 on the
full suite. Decisions worth recording:

- **The family lives in `jobs.db`**, derived at ingest time, not re-computed per read. Every
  reader (`review --list`, the bench in ticket 05, the exports) then gets it from one place,
  and re-tuning the guess needs a re-ingest rather than code in N readers.
- **`--queries` is a global option** next to `--data-dir`/`--db`, defaulting to
  `queries.txt`. It is a subcommand option on neither, because argparse cannot take a
  subparser's option before the subcommand word, and both `ingest` and `review --list`
  need it (the auto-ingest passes the same namespace through).
- **The table's columns are the union of every run file's header**, first-seen order. This
  matters more than it looks: the real `data/jobs_0.csv` is legacy (no `search_term` /
  `term_label`), so a first-header-only table would have had no `term_label` column at all
  and every row of a newer, correctly-labelled CSV would have silently degraded to
  `inferred`. `test_new_csv_columns_survive_a_legacy_csv_first_in_the_run` pins that.
- **Auto-ingest also fires on the index's shape, not just its mtime.** The `jobs.db` in
  this repo today was built before `job_family` existed; no CSV would ever move again, so
  the mtime check would keep serving a table the join cannot read.
- **A `search_term` found in the map with an empty `term_label` is `inferred`, not
  `stamped`**: the family was recovered from `queries.txt`, not recorded on the row, so it
  inherits the display-only guard. `guess_family` is the one matching function
  (case-insensitive substring, longest phrase wins, ties to the family listed first).
- **Real-data result:** 302 legacy rows → 74 `inferred`, 228 `(unknown)`. The miss rate is
  the vocabulary, not a bug: the catch-all family matches nationally, so the legacy set
  includes restaurants and bakeries no family terms. Those rows show `(unknown)` and stay
  in the queue — an inferred family is display-only and never grounds an exclusion rule.

**Review follow-up (same day).** Both axes re-ran the ticket; all six acceptance lines
PASS, with the two display guards verified by mutation (neutralising the stamp upgrade or
the headerless-term guard each fails a test). Seven findings were real and are fixed:

- `cmd_review` reported a missing index whenever no CSV was present, even against an intact
  `jobs.db`, and advised an ingest that could not succeed. It now only errors when both are
  missing, and leaves an index with no CSVs beside it alone rather than rebuilding it empty.
- The family-map load crashed with a traceback on an unreadable (non-UTF-8, or a directory)
  `--queries` path; it now degrades to the same no-map fallback as a missing file.
- A header-only run file hit a division by zero in the ingest summary, newly reachable
  through the auto-ingest. Guarded.
- The join reported `cannot open` for a CSV missing a display column, burying sqlite's own
  "no such column" message. It now says it cannot list the queue and passes the cause
  through.
- A row first seen by a legacy CSV kept its guessed family forever: the next scrape records
  the family for the same URL, and first-writer-wins dedup threw it away. A later stamp now
  replaces a guess on the same row (a stamp never replaces another stamp, so the first term
  to name a family keeps it and ticket 01's dedup is unchanged).
- `test_review_store.py` ran the CLI without `--db`, so the child process shared
  `/tmp/data/jobs.db` across runs — the review tests were not hermetic. Now explicit.
- The fixture had no headerless term, so the "absent from the map" rule was untested; added,
  along with a docstring that had overstated what (unknown) covers.
