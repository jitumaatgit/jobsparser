# Teaching Notes

Working notes for teaching dadbod/dadbod-ui in this workspace. Preferences and
decisions that steer future sessions.

## About the learner
- Experienced Neovim user on LazyVim; comfortable driving the editor. New to dadbod.
- **SQL: beginner.** Leaned on the `jobsview.py` CLI flags (`--match`, `--min-hourly`,
  `--sort`). Bridge every SQL concept to a flag they already know.
- Goal (confirmed): **browse the DBUI drawer AND write their own SQL** against
  `data/jobs.db`. Stated intent is *tool fluency* — `jobs.db` is the playground.
- Prefers reading data inside Neovim over a browser/CLI; that's the whole "why".
- Reads lessons **fullscreen in a browser on a laptop**. Lessons MUST look
  desktop-native — a responsive container that widens with the viewport, not a
  phone-width single column. (Fixed 2026-10-08: `assets/style.css` now scales
  44rem → 50/56/62rem at 1000/1300/1600px, with type that grows via `clamp()`.)

## How to teach here
- One tight win per lesson, tied to `data/jobs.db`. Keep within working memory.
- Give a single tangible thing they can do in Neovim before the lesson ends.
- Keep quiz **answer options equal length** (same word count, as close in characters
  as possible) so formatting never leaks the answer. Preserve this in every lesson.
- Always cite a primary source (`:help`, the plugin README, this repo) for claims.
- Constrain wide `pre`/`.out` blocks so they never clip at laptop widths (a short
  ASCII flow diagram, or `white-space: pre-wrap` — never let a diagram scroll-cut).

## Environment facts (verified 2026-10-08)
- Plugins: `tpope/vim-dadbod` + `kristijanhusak/vim-dadbod-ui`, lazy-loaded on the
  `:DBUI` command family. Connection `jobsparser` is pre-defined in `vim.g.dbs`.
- `sqlite3` 3.45.1 on PATH (required by dadbod's sqlite adapter). Neovim v0.12.4.
- **Verified interaction** (headless nvim, minimal rtp, their exact `g:dbs`):
  `:DBUI` → `o` `jobsparser` → `o` `Tables (7)` → `o` `jobs` → `o` `List` opens a
  SQL buffer pre-filled `SELECT * from "jobs" LIMIT 200;` → `:w` renders `.dbout`.
  Table helpers are `List, Columns, Primary Keys, Indexes, Foreign Keys`.
- Note: verified against the plugin code paths + their `g:dbs`, not a full LazyVim
  boot. If LazyVim lazy-load timing ever misbehaves, revisit.

## How lessons get opened (decided 2026-10-08)
- Zen Browser is the default `text/html` handler and is a **Flatpak**. Its Exec uses
  `--file-forwarding … @@u %u @@`, so `xdg-open <file>` routes the page through the
  xdg-desktop-portal **document portal**, exporting only that one file — the sibling
  `../assets/*` then 404 and the page renders **unstyled**. Zen's sandbox also has no
  access to `~/projects`. (The `Sandbox: CanCreateUserNamespace() … EPERM` line is
  Zen's own content-sandbox warning, *not* the cause.)
- **Chosen workflow (user preference):** the user runs `bash serve-lessons.sh` in a
  terminal and leaves it running, then opens the printed
  `http://127.0.0.1:8777/lessons/…` URL in Zen. Default port 8777; pass another if busy.
- Do **not** rely on: a supervised/agent-started server (harness services here are
  `persist=false` and died on port conflict), or `xdg-open` on the HTML file.
- Agent can't reach the GUI (no DISPLAY in the tool shell). For render proof use
  `google-chrome --headless=new --no-sandbox --screenshot=/tmp/x.png "file:///…html"`;
  verify layout at 1440px and 1920px widths.
- Lesson 2's "open me" step should say: `bash serve-lessons.sh` → open the URL.

## Open threads / next lessons
- LR-0002 target: writing the first real SQL in a SQL buffer (`:w` / `<Leader>S`),
  translating `jobsview.py new` → `ORDER BY date_posted DESC LIMIT`.
- Then `WHERE` (→ `--min-hourly`, `--company`), then FTS5 `MATCH` (→ `--match`).

## Lesson workspace files
- MISSION.md, RESOURCES.md, GLOSSARY.md, NOTES.md (this file)
- assets/style.css + assets/quiz.js (shared; link with `../assets/…` from lessons)
- lessons/0001-connect-and-browse-jobs-db.html
- reference/0001-dadbod-dbui-cheatsheet.html
- learning-records/0001-mission-and-dadbod-entry-point.md
- serve-lessons.sh (starts the local HTTP server; executable)
