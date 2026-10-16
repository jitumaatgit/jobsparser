Status: ready-for-agent
Type: task

# 08 — `kanban.md` export, with a migration gate

`jobsview kanban` writes the existing kanban.nvim board so it keeps working as a viewer.
The export overwrites the file. **Before this ticket is ever run, the one hand-added card
on the board must be re-entered in the bench — see the gate below.**

## Change

`jobsview.py`:

- New `kanban` subcommand, `--kanban` (default
  `~/notes/docs/90-archives/04-finding-employment-project/application-process/kanban.md`).
  Headless, no Textual import. Same union query as ticket 07.
- Emit `kanban-plugin: basic` frontmatter, then the sections in this order with the
  `## Name` heads the plugin expects: `## Interested`, `## Applied`, `## Interview`,
  `## Offer`, `## Rejection`, `## Withdrawn`.
- Map application status to section: `none` → `Interested`, `applied` → `Applied`,
  `interview` → `Interview`, `offer` → `Offer`, `rejected` → `Rejection`, `withdrawn` →
  the new `## Withdrawn`. Card text is `- [ ] <title> — <company>`.
- **Only kept rows appear on the board.** False positives and unreviewed rows are absent.
- `## Withdrawn` is a new section — preserve the existing frontmatter block and closing
  `%% kanban:settings %%` block byte for byte so the plugin still parses the file.
- Write atomically (temp file + `os.replace`) so an interrupted run cannot leave a
  half-written board.

## Migration gate — do not skip

The board currently contains one hand-added card, `gardencenter` under `## Applied`. This
export overwrites the whole file, so running it before `gardencenter` (and any other card
not in the bench) is in `review.db` **destroys that card**. The export is one-way by
deliberate choice, and no code may paper over it.

Adding the card to the bench is a human step — the card's `job_url` is not on the board.
The implementer must surface this stop condition and not run the export as a smoke test
against the real path.

## Acceptance

- Unit tests write to a temp file, never the default path. No test may pass the real
  `--kanban` default.
- A fixture with one row per status produces 6 sections in order, one card each, with the
  frontmatter and `%% kanban:settings %%` blocks intact.
- A fixture with `false_positive` and `unreviewed` rows produces an empty board.
- `withdrawn` maps to `## Withdrawn`, and no other status lands there.
- Re-running after a status change moves the card between sections rather than duplicating it.

## Blocked by

[05](05-bench-tui.md), and the migration gate above.
