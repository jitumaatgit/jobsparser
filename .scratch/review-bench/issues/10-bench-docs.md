Status: resolved
Type: task

# 10 — Document the review bench

The bench is now how the review pass happens. The README still describes it as not
existing, and `CONTRIBUTING.md` says nothing about it.

## Change

- `README.md`: replace the "A TUI around the scrape would be a nicer way to watch
  something that already runs unattended" framing if any of it remains, and add a
  **Review bench** section under *Querying the results*: `make bench-setup`,
  `python3 jobsview.py review`, the two axes, `data/survivors.csv`, and the kanban export
  with its one-way caveat. Keep the Datasette and dadbod sections — both stay as an
  optional SQL escape hatch.
- `CONTRIBUTING.md`: one short section — `make setup` for the CLI, `make bench-setup` if
  you want the bench, and the note that `jobsview.py`'s other subcommands need no install
  at all.
- `CONTEXT.md` is already updated and needs nothing.
- `docs/adr/0002-replace-sheets-review-pipeline.md` — confirm the file matches what was
  actually built and add a **Superseded by** frontmatter line pointing at the successor if
  any decision changed during implementation.

## Acceptance

- A reader of `README.md` can go from clone to a working review pass using only the
  documented commands.
- The kanban export's one-way, overwrite nature and the `gardencenter` gate are stated in
  the README, not just in the spec.
- No mention of Google Sheets as part of the live pipeline remains anywhere in the repo
  docs.

## Blocked by

[05](05-bench-tui.md), [07](07-survivors-export.md), [08](08-kanban-export.md)


## Comments

**2026-10-16.** Implemented. README restructured into a single Review bench
section (two axes, setup, keys, narrowing, survivors export, kanban export with
one-way caveat, SQL escape hatch). CONTRIBUTING.md added with setup split.
No Google Sheets mention remains in live docs.
