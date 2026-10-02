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

## Notes

- The CSV is rewritten after every search term, so a long multi-term run keeps completed
  results if a later term fails.
- JobSpy is installed from git. Pin it in `jobsparser/pyproject.toml` if upstream
  breaking changes become a problem.
- Keep `--sleep-time` non-trivial; going too fast gets you rate-limited.