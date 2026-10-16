# Mission: Browse and query the job database from inside Neovim

## Why
The ~300 job postings scraped by `jobsparser` land in `data/jobs.db`. Today they're
read by paging the `jobsview.py` CLI or by leaving the terminal for a Datasette server
in a browser. The user prefers reading in Neovim and wants to search, filter, and open
listings against the real dataset without context-switching — vim-dadbod + vim-dadbod-ui
are now installed for exactly this.

## Success looks like
- Open Neovim, run `:DBUI`, and see the saved `jobsparser` connection point at `data/jobs.db`
- Browse the `jobs` table in the drawer and read rows in the `.dbout` buffer
- Write a hand-authored SQL query in an SQL buffer and run it to pull exact rows
- Translate what they already do with `jobsview.py` flags (newest, `--min-hourly`, `--match`) into SQL
- Re-run `make index` after a scrape and query the refreshed data without re-setup

## Constraints
- **SQL: beginner.** They leaned on the `jobsview.py` CLI flags; teach SQL incrementally,
  using those flags as the bridge to `SELECT`/`WHERE`/`ORDER BY`.
- Plugins are already installed on LazyVim, lazy-loaded on the `:DBUI` family of commands.
  A named `jobsparser` connection is already defined in `vim.g.dbs` — no `DBUI_URL` needed.
- Goal is fluency with the tool; `jobs.db` is the playground, not a specific task.
- Requires the `sqlite3` CLI on `PATH` (dadbod's SQLite adapter shells out to it). Present (3.45.1).

## Out of scope
- Writing to the database (`INSERT`/`UPDATE`/`DELETE`) — read-only browsing for now.
- Non-SQLite adapters (PostgreSQL/MySQL) — this file is the target.
- Full-text-index internals beyond issuing `MATCH` queries.
