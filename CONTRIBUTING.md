# Contributing

## Setup

```bash
make setup        # CLI only: venv + editable install of jobsparser
make bench-setup  # adds Textual, needed for `jobsview review`
```

`jobsview.py`'s other subcommands (`ingest`, `stats`, `search`, `new`,
`export`, `kanban`, `review --list`) need no install at all — they run on the
standard library.
