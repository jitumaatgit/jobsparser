# Neovim + vim-dadbod Glossary

The vocabulary for browsing and querying `data/jobs.db` from inside Neovim with
vim-dadbod and vim-dadbod-ui. Lessons and the cheat sheet use exactly these words.

## Connections & addresses

**Connection**:
A named entry that tells dadbod which database to open, stored as a URL. This
workspace has one: `jobsparser` → `sqlite:/home/mint/projects/jobsparser-fork/data/jobs.db`.
_Avoid_: database, server — a connection is the local handle, not the database itself.

**URL (connection URL)**:
The `adapter:target` string naming a database, e.g. `sqlite:/abs/path` or
`sqlite:relative/path`. dadbod reads the scheme to pick the adapter.
_Avoid_: DSN, connection string (unless quoting the docs).

**Adapter**:
The code dadbod uses to speak a database's protocol, chosen from the URL scheme
(`sqlite`, `postgresql`, `mysql`, …). The `sqlite` adapter shells out to the
`sqlite3` command-line program, which must be on `PATH`.
_Avoid_: driver, client.

**`g:dbs`**:
The global list of named connections. This workspace defines `jobsparser` here in
`~/.config/nvim/lua/plugins/jobsparser-db.lua`, so no `$DBUI_URL` is needed.
_Avoid_: the connections file (that is the other source, keyed `A`/`~/.local/share/db_ui`).

## The drawer

**Drawer**:
The left navigation pane vim-dadbod-ui opens with `:DBUI`. It lists connections,
their tables, your query buffers, and saved queries.
_Avoid_: sidebar, explorer, file tree.

**`o` / `Enter` (open or toggle)**:
The primary drawer action. On a collapsed node it expands (connecting if it is a
connection); on an expanded node it collapses. Mapped to `<Plug>(DBUI_SelectLine)`.
_Avoid_: expand/click (as verbs for this key) — say "open with `o`".

**`?` (in-drawer help)**:
Shows the drawer's available mappings. `q` closes the drawer.
_Avoid_: man, docs (that is `:help`).

## Tables & queries

**Table helper**:
A predefined named query attached to a table. A SQLite table exposes `List`,
`Columns`, `Primary Keys`, `Indexes`, and `Foreign Keys`.
_Avoid_: action, view, preset.

**List helper**:
The default row-listing table helper. Opening it creates a SQL buffer pre-filled
with the listing query — by default `SELECT * from "jobs" LIMIT 200;`.
_Avoid_: preview, browse, "the table view" — say "the List helper".

**SQL buffer**:
A scratch SQL buffer (filetype `sql`) where you write a query. Opening a table helper
creates one pre-filled; running the query is done by writing the buffer.
_Avoid_: query window, editor pane.

**dbout buffer (`.dbout`)**:
The read-only results buffer where an executed query renders as a grid of rows.
_Avoid_: results window, output pane.

**Execute on save**:
dadbod-ui runs a SQL buffer when you write it (`:w`). Distinct from auto-executing
table helpers, which is off by default.
_Avoid_: "it runs automatically" — opening a helper does **not** run it; `:w` does.

**Saved query**:
A query persisted from a SQL buffer (`<Leader>W`) so it reappears under a
connection's `Saved queries`.
_Avoid_: snippet, bookmark.

## Ambiguities

- **"Open" a table** in the drawer means expand to show its helpers — it runs
  nothing by itself. In this workspace, "browse the jobs table" always means the
  List helper.
- **`o`** is a toggle: on an already-open node it collapses rather than re-running.
