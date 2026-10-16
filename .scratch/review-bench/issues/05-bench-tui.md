Status: resolved
Type: task

# 05 — The review bench TUI

`jobsview review` — a Textual app with the flat queue, list/detail panes, the two-axis
keys and undo. The first screen must render on a real terminal before ticket 06 starts.

## Change

`jobsview.py`:

- New `review` subcommand. If no CSV changes, it runs headless-compatible setup from
  ticket 04, then launches the Textual app.
- Layout: a left `DataTable` (title, company, location, date, pay, family, decision,
  status) and a right `RichLog`/`Markdown` detail pane showing the description plus the
  direct URL and provenance. The table is virtual — thousands of rows must stay smooth.
- **Queue**: default filter is `decision = unreviewed`. Auto-advance to the next
  unreviewed row after any action. `j/k` and arrow keys move; `enter` focuses detail;
  `v` opens `job_url_direct` falling back to `job_url` via `webbrowser`.
- **Review decision** (`space` cycles `unreviewed → keep → false_positive → unreviewed`),
  plus direct keys so a long session does not need cycling.
- **Application status**: one key per status (`a` applied, `i` interview, `o` offer,
  `r` rejected, `w` withdrawn, `0`/`n` none).
- **Undo**: `Ctrl-Z` pops the last action and restores the row, with a footer line showing
  what was undone. Keep an in-memory stack of `(job_url, previous decision, previous
  application_status)` — no history file.
- A status bar with counts: unreviewed remaining, kept, false positives.
- Header shows the current filters so a narrowed queue is never mistaken for the whole set.

`Makefile`: add a `bench-setup` target that installs Textual into `.venv`
(`.venv/bin/pip install 'textual>=8.2.8'`). Do not add Textual to `jobsparser`'s
dependencies and do not touch `setup`/`scrape`/`index`/`view`/`clean`. README and
CONTRIBUTING get a short section: `make bench-setup`, then `python3 jobsview.py review`.

`jobsview.py`'s other four subcommands stay stdlib-only. Import Textual inside the
`review` command, so `jobsview search` still runs where Textual is not installed, and exit
with a one-line "run: make bench-setup" if the import fails.

## Acceptance

- Headless `App.run_test()` (async pilot): the app starts, the table is populated from a
  fixture DB, `space` changes the decision and advances the cursor to the next unreviewed
  row, `Ctrl-Z` restores both the previous decision and the previous application status
  and moves the cursor back.
- The decision and application status keys write through to `data/review.db`.
- `jobsview search` still runs in an environment where `textual` is not installed, and
  `jobsview review` there exits with the `make bench-setup` message.
- 2000 fixture rows render and advance without noticeable lag.

## Blocked by

[04](04-ingest-and-families.md), and `make bench-setup` from this ticket.

**Stop condition.** After this ticket renders, confirm the first screen on a real terminal
before starting 06 — see ticket 09.

## Comments

**2026-10-08.** All four acceptance lines verified. The TUI lives in `jobsview_tui.py`
(Textual imported there, and `textual` itself imported inside `cmd_review`), so
`jobsview.py` stays stdlib-only: `search`/`new`/`stats` run under `python -S`, and
`jobsview review` there prints one line and exits 1 rather than a traceback. `make
bench-setup` installs `textual>=8.2.8` into `.venv`; `jobsparser/pyproject.toml` is
untouched.

Tests: `jobsparser/tests/test_review_bench.py` (7) — the pilot test drives the real
`review.db` through `space`/status keys/`Ctrl-Z`, and the store is asserted through
`jobsview review --list` rather than by reaching into sqlite. Full suite 52/52.

Decisions worth recording:

- **The queue is the unreviewed rows, and an action mutates the table in place.** A
  decision removes one row (`remove_row`); a status change repaints three cells
  (`update_cell`). Rebuilding the table per keystroke is the easy mistake here, so a test
  watches `DataTable.add_row` and fails if a single action calls it. Measured cost is flat
  in queue size — 124 ms/press at 200 rows, 129 ms at 2000 — which is what "thousands of
  rows stay smooth" actually means.
- **The detail pane renders exactly once per cursor move.** `move_cursor` fires
  `RowHighlighted`, which repaints the pane; calling `_show_detail` beside it as well
  rendered the markdown twice per keystroke. `_place_cursor` relies on the event and only
  repaints explicitly when the cursor does not move.
- **Undo rebuilds; nothing else does.** `Ctrl-Z` is rare and must put the restored row
  back in its original position, which an append cannot do, so it reloads the queue. The
  stack is `(job_url, previous decision, previous application status)` in memory only, per
  spec — no history file.
- **`v` prefers `job_url_direct`** and falls back to `job_url`, tested against a row with
  an empty direct link.
- **Auto-advance after *any* action**, status keys included: the cursor lands on the row
  now at the acted index (removal) or the next row (in-place change).

Rendering is **not** claimed from here: this session is `TERM=dumb`. Ticket 09 is the
human check of the first screen, and 06 is blocked on it.

**Two-axis review (same day).** Both axes ran independently. Four findings were real and
are fixed; two are recorded rather than fixed, with reasons.

Fixed:

- **The suite stopped being discoverable without Textual.** `test_review_bench.py`
  imported Textual at module level, so `make setup` without `make bench-setup` — the
  environment CONTRIBUTING promises works — failed discovery. The bench class is now
  `@BENCH`-skipped with the message `run: make bench-setup`, and the one test that exists
  *because* Textual may be absent (the stdlib-only guarantee) moved into its own
  always-running class. Verified by blocking `textual`/`rich` at import: 53 tests, 7
  skipped, green.
- **The launch instructions named the wrong interpreter.** README and CONTRIBUTING said
  `python3 jobsview.py review`; `make bench-setup` installs into `.venv`, and the system
  `python3` has neither Textual nor the package. Both now say
  `.venv/bin/python jobsview.py review`, matching CONTRIBUTING's existing rule.
- **"Triage" is on `CONTEXT.md`'s avoid list** as a synonym for the review decision. The
  `review` subcommand help said "triage the queue"; it now says "work the queue". (One
  further instance in README's opening paragraph predates this ticket and is left alone.)
- **A key that changed nothing did not advance.** Pressing `0` on a row already at `none`
  returned early, so "auto-advance after *any* action" held for every key except the ones
  that happened to be no-ops. It now advances, writes no store row, and pushes nothing
  onto the undo stack.

Recorded, not fixed:

- **Filters are ticket 06's scope, not 05's.** `spec.md`'s Interaction section describes
  the bench end to end, including a family filter and title/company search; ticket 06 is
  the filters ticket and is blocked on 09. This ticket's own Change section asks only for
  the header to *show* the filters so a narrowed queue is not mistaken for the whole set.
  The header does that, and the queue is unreviewed-only.
- **`space`'s cycle and auto-advance pull against each other.** The ticket asks for both
  `space` cycling `unreviewed → keep → false_positive → unreviewed` and for the cursor to
  advance after any action. On an unreviewed-only queue, one `space` press sets `keep`,
  the row leaves the queue, and the cursor moves on — so a single row cannot be cycled
  twice in a row. Both requirements are implemented as written; the cycle becomes
  observable once 06 can filter to decided rows (a `keep` row cycles to `false_positive`,
  and a `false_positive` row back to `unreviewed`). Direct keys (`y`/`f`/`u`) cover the
  long session the ticket mentions.
