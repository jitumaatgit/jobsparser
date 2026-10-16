Status: resolved
Type: task

# 06 — Filters inside the bench

Search over title/company, plus family and decision-state filters, so a 300-row queue can
be narrowed without leaving the TUI. The TUI must already render on a real terminal.

## Change

`jobsview.py`:

- A filter bar driven by `/` for a search term (title and company, `LIKE`, matching what
  `jobsview search --match` does today — reuse the existing query-building code rather than
  writing a second one).
- `f` cycles the family filter over the families present in the queue, including
  `(unknown)`; `d` cycles the decision filter (`unreviewed` / `keep` / `false_positive` /
  all).
- Filters are applied to the existing in-memory list, not by re-querying SQLite — keep the
  original row order and the cursor's position within the filtered set.
- The header shows every active filter (search text, family, decision) so a narrowed queue
  is never mistaken for the whole set. `Esc` clears them.
- Treat the combination as a conjunction; an empty search string means no search filter.

## Acceptance

- Headless `run_test()` pilot: with three rows, opening `/`, typing a company fragment and
  confirming leaves only the matching rows; `f` narrows to one family and shows it in the
  header; `Esc` restores the full queue.
- `d` cycling through `unreviewed` shows only unreviewed rows, then only kept, and back to all.
- Filtering does not reorder the queue, and the cursor stays on the same row when it is
  still visible.
- Search matches title and company but not description, matching `jobsview search --match`
  minus FTS.

## Comments

**2026-10-10.** Implemented and verified. `jobsview.py` gains `matches_search`
(with `_like_pattern`/`_like_matches`), the one definition of what a search term
means — `_build_query`'s LIKE clauses now build their params with the same
`_like_pattern`, so the CLI and the bench cannot drift. `jobsview_tui.py` gains
the filter state, the `/` bar, `f`, `d` and `Escape`.

Verified: 22 tests in `test_review_bench.py` (7 new), full suite green, and a
real `xterm-256color` pty on the 302-row index at 140×40 — the bar opens and
closes, typing narrows by title/company, `f` cycles the families present, `d`
cycles the decision states, `Esc` restores the full queue, and all eleven shown
bindings (Search, Family, Decided, Clear, Undo, Quit included) fit the footer
without dropping any. Re-checked at 62×28 with the bar open: the header clips to
one line rather than wrapping, and the counts/filter lines stay readable.

Decisions worth recording:

- **`f` moved off the false-positive key.** Ticket 05 bound `f` to
  `false_positive`; ticket 06 needs `f` for the family filter. The direct
  reject key is now `x`, and every doc/test that named `f` was updated. `space`
  still cycles all three decisions for anyone who reaches for the old key.
- **The family cycle walks the families the *other* filters leave**, then wraps
  back to all of them, so there is always a way out without clearing the search
  term. `(unknown)` sorts last rather than first. The filter matches the raw
  family, so a stamped and an inferred row of one family are never split.
- **A decision now only leaves the queue if the filters say so.** `_in_queue`
  is the single conjunction, used both to rebuild the queue and to decide
  whether an acted row stays visible — so on a `keep`/`all` queue a row that
  gains a decision is repainted in place, which is what makes `space`'s
  three-state cycle observable (ticket 05 recorded that it could not be).
- **Textual's `run_action` reads `check_action` as a plain truth value.** A
  `None` ("no opinion" per the API docs) silently disables the action, so the
  override that gates the queue's keys while the bar has focus must return a
  bool. Returning `None` broke every binding in the app, not just the gated
  ones — worth knowing before the next dynamic-binding need.
- **A filter change rebuilds the table; an action never does.** Ticket 05's
  no-rebuild test still passes unchanged, because it drives a decision key.
  Rebuilding is confined to `_fill_table`, which also preserves the cursor's
  row (or its position when that row is gone).
- **The search bar is hidden until `/` and closed again on Enter**, so it costs
  no screen line in normal use; the header keeps the active term visible.
  Priority bindings are checked before the focused widget, so the queue's keys
  are disabled while the bar has focus — otherwise every letter of a term would
  drive the queue instead of the bar.

## Blocked by

[05](05-bench-tui.md), and ticket [09](09-terminal-verify.md) must be done first.

## Comments — 2026-10-10 (code review pass)

Reviewed the bench across correctness, readability, security and performance. Four
defects found and fixed, each with a regression test proven to fail without its fix.

- **Unescaped console markup (security, the important one).** Every widget that
  renders untrusted text — the search term in the header, and job titles in the
  queue — was parsed as console markup, because a `Static` defaults to
  `markup=True` and `DataTable` parses `str` cells the same way. A title or a
  typed term containing `[/red]` raised `MarkupError` inside a keystroke
  handler; `[foo]bar` was silently rendered as `bar`. It is also an
  arbitrary-style-injection channel, since `[bold red]…[/]` is honoured. Fixed by
  rendering those labels with `markup=False` and building every queue cell as
  `rich.text.Text` (`_display_row`, and the three in-place cell updates in
  `_refresh_row`).
- **The bench's LIKE silently diverged from the CLI's.** `_like_matches` used
  `re.IGNORECASE` without `re.ASCII`, so Python's Unicode folding made the bench
  a strict superset of SQLite's ASCII-only `LIKE`: a term `k` matched U+212A
  (KELVIN SIGN) in the TUI and 0 rows in `jobsview search`. `re.ASCII` restored;
  `test_search_semantics_stay_stdlib_only` pins both directions.
- **`undo` hid a restored row with no explanation.** Restoring `unreviewed`
  while a filter excluded it made the row vanish, which reads as a lost job.
  The status bar now states the cause and how to reveal it. The first version of
  that note blamed the decision filter for whatever hid the row and pointed at
  `d`; a review comment corrected it — the note now names each active filter the
  row actually fails (decision, family and/or search, in header order), and
  points at `Esc`, because one `d` from `keep` lands on `false_positive` and
  still hides an unreviewed row.
- **The note stays silent when the undo restores a row the filters already
  admit**, rather than inventing a cause for a row that is plainly visible.

Verification: 71 tests in `test_review_bench.py`, full suite green, plus a real
`xterm-256color` pty drive on the 302-row index — typing `[/][/red]cash` in the
bar leaves the literal term in the header with no `MarkupError`, and `y` → `f` →
`Ctrl+Z` prints `Undid … — not in the queue: hidden by job family=…; Esc clears
it`, with the sidecar showing the restored `unreviewed` decision afterwards.
(Note for future pty harnesses: `Ctrl+Z` is `0x1A`, not `0x16`, which Textual maps
to `Ctrl+V`.)
