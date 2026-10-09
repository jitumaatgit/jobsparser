# Contributing

This is a personal fork. It runs from source and is **not published to PyPI** — there is
no build, publish, or release process here.

## Setup

```bash
make setup
```

That creates `.venv` and installs the CLI in editable mode along with
[python-jobspy](https://github.com/speedyapply/JobSpy) from git.

## Running

```bash
.venv/bin/jobsparser --search-term '"data entry"' --location "Portland, OR" \
  --results-wanted 600 --batch-size 100 --sleep-time 60 --hours-old 24 \
  --indeed-country US --output-dir data
```

Or via make:

```bash
make scrape SEARCH_TERM='"data entry"' LOCATION="Portland, OR"
```

`make scrape` accepts `RESULTS_WANTED`, `BATCH_SIZE`, `SLEEP_TIME`, `HOURS_OLD`,
`INDEED_COUNTRY`, `DISTANCE` and `OUTPUT_DIR` as make variables, each defaulting to the
values above.

`--term-label` records the job family each row came from — one label per search term,
paired by position, so the CSV stays self-describing:

```bash
.venv/bin/jobsparser \
  --search-term '("retail" OR cashier)' --term-label 'Retail, Logistics & Specialized Trades' \
  --search-term '("help desk" OR "data entry")' --term-label 'IT, Office & Documentation' \
  --location "Portland, OR" --results-wanted 600 --output-dir data
```

Omit it and every row gets an empty `term_label`; give a different number of labels than
search terms and the run fails with a usage error before anything is scraped.

## Tests

Plain `unittest` — no pytest, no extra install:

```bash
.venv/bin/python -m unittest discover -s jobsparser/tests
```

Use the venv interpreter: the system `python3` has no `jobsparser` installed. Each test
stubs `scrape_jobs` at the network boundary and asserts on the CSV that gets written, so
the suite is offline and deterministic. New test modules need the `sys.path` shim at the
top of `test_cli_provenance.py` — the stub `jobsparser/__init__.py` at the
project-directory root shadows the real package whenever the repo root is the working
directory.

The files under `.scratch/fork-assessment/` are **not** a test suite. They are live
probes against Indeed that print findings and assert nothing; each one costs real
requests, so run them by hand.

## Review bench

`jobsview review` is a Textual TUI. Textual is **not** a dependency of the `jobsparser`
package and is never added to `jobsparser/pyproject.toml`; install it into `.venv` on its
own:

```bash
make bench-setup
.venv/bin/python jobsview.py review
```

`jobsview.py`'s other subcommands stay stdlib-only. The TUI lives in `jobsview_tui.py` and
Textual is imported inside the `review` command, so `jobsview search` still runs where
Textual is not installed, and `jobsview review` there exits with a one-line
`make bench-setup` message instead of a traceback.

Decisions and application statuses are written to `data/review.db`, a sidecar keyed on
`job_url` — never to `data/jobs.db`, which `jobsview ingest` unlinks and rebuilds. The TUI
is exercised headlessly in `test_review_bench.py` with Textual's `App.run_test()` pilot;
that covers the queue, the keys and undo without a terminal.

## Notes

- The CSV is rewritten after every search term, so a long multi-term run keeps completed
  results if a later term fails.
- JobSpy is installed from git. Pin it in `jobsparser/pyproject.toml` if upstream
  breaking changes become a problem.
- Keep `--sleep-time` non-trivial; going too fast gets you rate-limited.