Status: resolved
Type: task

# 02 — Pass family labels from `queries.txt`

`run_queries.sh` derives each family label from the `# --- Family ---` header above its
search term and passes it as `--term-label`. The label *is* the job family, and
`queries.txt` remains the only file that is edited.

## Change

`run_queries.sh`:

- Walk `queries.txt` line by line. A non-comment, non-blank line is one search term; the
  label is the text of the nearest preceding `# --- <Family> ---` header. Order the terms
  and their labels together so `--search-term A --search-term A-label` stay paired.
- Pass `--term-label "$label"` for every collected term. Terms whose header is missing get
  `''`.
- Keep the existing env overrides (`RESULTS_WANTED`, `LOCATION`, …) and the "no active
  terms" exit unchanged.
- `set -u` is already on; the word-splitting must survive a term label containing spaces,
  commas and ampersands — quote every expansion.
- Note in `queries.txt`'s header comment (2 lines, not more) that each `# --- Family ---`
  header is now the `--term-label` for the term below it, so an unnamed family is not a
  silent surprise later.

## Acceptance

- `./run_queries.sh` with a stub `.venv/bin/jobsparser` that prints its argv shows one `--search-term`/`--term-label` pair per active term, labels matching their `# --- Family ---` headers, and `--term-label ''` for an unlabelled term.
- Labels containing spaces and commas arrive as single argv entries (no word splitting).
- Commented-out terms contribute neither a term nor a label.
- The existing "No active search terms in $QUERIES_FILE" path still exits non-zero.
- `RESULTS_WANTED=1 ./run_queries.sh` still triggers the estimated-time banner.

## Blocked by

[01](01-cli-provenance.md) — `--term-label` must exist.

## Comments

**2026-10-08 — implemented and verified by running it.**

`run_queries.sh` walks `queries.txt` once with a `while IFS= read -r line` loop: a
line matching `# --- … ---` sets the current family label, comment and blank lines
are skipped, and every other line is one search term carrying the label of the
nearest preceding header. Terms and labels accumulate in parallel arrays and are
re-joined index by index, so a label holding spaces, commas or an `&` reaches the
CLI as a single argument, and a term with no header above it still gets
`--term-label` with an empty value. The `grep`/`mapfile` collection is gone; the
env overrides, the comments-only exit and the estimated-time banner are unchanged.

Verification, all against a stub `.venv/bin/jobsparser` that prints its argv (no
requests): 5 unit tests in `jobsparser/tests/test_run_queries_labels.py` covering
pairing, single-argument labels, commented-out terms, the no-active-terms exit and
the `RESULTS_WANTED=1` banner; plus a smoke run of the real script on the real
`queries.txt` — 5 families with labels exactly the 5 headers, terms byte-identical
to the active lines, `--term-label ''` for a term before any header, exit 1 with
`No active search terms` for a comments-only file, and
`Running 5 search term(s) … 1 results each` under `RESULTS_WANTED=1`. Full suite:
11 tests, OK.

One thing to remember: the label is the nearest preceding header *only*, so a term
added under another family's term with no header of its own silently files itself
under that family. The caveat comments already inside families (family 1's
"truncated in your notes" note, the catch-all's `NOTE:` block) sit between header
and term and correctly leave the label alone.

**Review follow-up (same day).** Both review axes independently found one real hole: a
header carrying a trailing space or a carriage return matched neither the header branch
nor the comment branch, so it was skipped as an ordinary comment and the term beneath it
silently inherited the *previous* family's label — wrong provenance on real CSV rows.
The line is now trimmed at both ends before the comparison, the new test
`test_a_header_with_stray_trailing_whitespace_still_names_its_family` covers a trailing
space and a `\r` through subTest, and the `queries.txt` note no longer promises `''` for
any headerless term: only a term *before* the first header gets that, since a term added
under a family inherits it. Verified: 12/12 tests plus a stub run of the reviewers'
exact reproduction, where a `# --- IT --- ` header after a Retail family now labels its
term `IT, Office & Documentation` instead of `Retail`.
