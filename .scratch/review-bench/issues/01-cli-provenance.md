Status: resolved
Type: task

# 01 — Stamp provenance on every scraped row

`jobsparser` gains an optional `--term-label` and every CSV row carries the search term
that produced it. This is the only CLI change in the feature.

## Change

`jobsparser/src/jobsparser/cli.py`:

- Add `--term-label`, `multiple=True`, same shape and default (`None`) as `--search-term`.
  The pair is positional by index — the first search term's label is the first
  `--term-label` value. Raise a usage error if `--term-label` is given a different count
  than `--search-term`.
- Thread the label into `_scrape_single_site` and stamp it onto every record it returns,
  alongside the verbatim search term.
- Add `search_term` (the raw `--search-term` value) and `term_label` to the DataFrame in
  `persist_progress`, so both columns are in the CSV header and every row. `term_label` is
  the empty string when no label was supplied — never `None`, never a placeholder.

Existing behaviour is otherwise untouched: batching, retry/backoff, per-term persistence,
URL dedup, `persist_progress`, the failed-term exit code.

Also document `--term-label` in `README.md`'s Use section and `CONTRIBUTING.md`.

## Acceptance

- `.venv/bin/jobsparser --search-term '"data entry"' --term-label 'IT, Office & Documentation' --location "Portland, OR" --results-wanted 1 --batch-size 1 --sleep-time 1 --output-dir data` writes a CSV whose header includes `search_term` and `term_label`, with the raw term and the label on the row.
- Omitting `--term-label` still works and yields `term_label` of `''` on every row.
- `--search-term A --search-term B --term-label L1` fails with a usage error naming the count mismatch.
- A multi-term run persists after each term exactly as before (per-`search_term` dedup unchanged).
- `python3 jobsview.py ingest` over a CSV produced with labels still succeeds unchanged.

## Blocked by

Nothing.

## Comments

**2026-10-08 — implemented and verified by running it.**

`--term-label` (`multiple=True`) pairs with `--search-term` by position. A count mismatch
raises a Click usage error before the output directory exists, so a mis-paired run cannot
half-complete. `_scrape_single_site` stamps `search_term` and `term_label` on each record
as it is produced, so both columns reach the CSV through the existing `persist_progress`
— one place to stamp, nothing to keep in sync.

Verification: 6 offline tests in `jobsparser/tests/test_cli_provenance.py` (stub at the
`scrape_jobs` network boundary, assertions on the parsed CSV); a live one-result run with
and without a label; the mismatch case against the real binary (exit 2, nothing written);
`jobsview.py ingest` over labelled CSVs (both columns land in `jobs`); and the pre-existing
`.scratch/fork-assessment/test_incremental.py` unchanged (exit 1, 8 surviving rows, no
duplicate URLs).

Two things worth knowing before ticket 02:

- Tests must force `jobsparser/src` to the front of `sys.path`. The tracked stub
  `jobsparser/__init__.py` at the project-directory root shadows the installed package
  whenever the repo root is the working directory, and the editable install's `.pth`
  entry sits behind the current directory. The shim is at the top of the test module.
- Prove the pairing with a stub CLI that prints its argv rather than a live multi-term
  run; the labels can then be asserted without spending requests.
