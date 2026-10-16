# Neovim + vim-dadbod Resources

## Knowledge

- [Plugin: vim-dadbod — tpope](https://github.com/tpope/vim-dadbod)
  The query engine underneath everything. Defines `:DB`, the URL/adapter model, and the
  `g:db` default connection. Use for: how a connection is addressed, running ad-hoc SQL.
  Canonical: `:help dadbod`.
- [Plugin: vim-dadbod-ui — kristijanhusak](https://github.com/kristijanhusak/vim-dadbod-ui)
  The drawer UI on top of dadbod: connections, table helpers, saved queries, buffers.
  Use for: everything clickable. Canonical: `:help vim-dadbod-ui`.
- [Video: "Dadbod UI" presentation by TJ DeVries](https://www.youtube.com/watch?v=ALGBuFLzDSA)
  Visual walkthrough of the drawer and table helpers. Linked from the plugin README.
  Use for: seeing the whole flow once before doing it yourself.
- [Companion: vim-dadbod-completion — kristijanhusak](https://github.com/kristijanhusak/vim-dadbod-completion)
  Optional SQL autocompletion inside the SQL buffers. Use later, once hand-writing queries.
- [CLI: SQLite command-line shell](https://sqlite.org/cli.html)
  vim-dadbod's `sqlite` adapter shells out to the `sqlite3` binary, so it must be on `PATH`.
  Use for: the same queries outside Neovim, and for sanity-checking what dadbod returns.
- [Internal: jobsparser README → "Browse in Neovim"](../../README.md) (lines ~84-106)
  The repo's documented intent for this exact workflow, plus a worked FTS5 SQL example.
  Use for: the local `make index` / `:DBUI` loop and the data's schema.

## Wisdom (Communities)

- [r/neovim](https://reddit.com/r/neovim)
  Active, high-signal Neovim community. Use for: plugin troubleshooting and workflow ideas.
- [vim-dadbod-ui GitHub issues](https://github.com/kristijanhusak/vim-dadbod-ui/issues)
  Author-maintained, narrow scope. Use for: behavior questions not settled by `:help`.

## Gaps

- No canonical "SQL for total beginners, learned through dadbod" course. Bridging the
  `jobsview.py` flags to SQL is lesson-local and self-authored here — flag later if a
  better general SQL resource should anchor it.
