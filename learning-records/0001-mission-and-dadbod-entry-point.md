# Learning Records

## LR-0001 — Mission and entry point for learning vim-dadbod / dadbod-ui

The learner wants to **browse the DBUI drawer and write their own SQL** against
`data/jobs.db` from inside Neovim (not Datasette, not the `jobsview.py` CLI). Stated
intent is tool fluency; `jobs.db` is the playground. SQL level is **beginner** — they
leaned on the `jobsview.py` flags (`--match`, `--min-hourly`, `--sort`) rather than
writing SQL, so new SQL should always be introduced as a translation of a flag they
already know. Mission captured in [MISSION.md](../../MISSION.md).

**Verified interaction model** (headless nvim, their exact `vim.g.dbs`, plugin
versions on disk): `:DBUI` lists the `jobsparser` connection; `o` expands
`jobsparser ✓ → New query / Saved queries (0) / Tables (7)`; `o` on `Tables` lists the
seven tables; `o` on a table expands its **helpers** (`List, Columns, Primary Keys,
Indexes, Foreign Keys`); `o` on `List` opens a `sql` buffer pre-filled
`SELECT * from "jobs" LIMIT 200;`; saving it (`:w`) renders a `.dbout` grid of all 302
rows. Key defaults: opening a helper does **not** auto-run; saving runs it. Prereq:
`sqlite3` CLI on `PATH` (3.45.1 present).

**Implications.** This sets the floor: they can now reach for `:DBUI` as a first-class
job-search surface. The next sessions should follow the flag→SQL bridge — lesson 2 is
writing the first hand-authored SQL in a buffer (`jobsview.py new` →
`... ORDER BY date_posted DESC LIMIT n`), lesson 3 `WHERE` (`--min-hourly`,
`--company`), lesson 4 the FTS5 `MATCH` path (`--match`). Because they've only been
shown *reading* so far, don't introduce `INSERT`/`UPDATE` without checking the mission.
