# jobsparser

A CLI that scrapes **Indeed** for hand-written boolean search queries and writes CSV
for a Google Sheets review pipeline.

This package is a thin CLI. The scraping itself comes from
[python-jobspy](https://github.com/speedyapply/JobSpy), the actively maintained JobSpy
library, which is installed from git.

## Install

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ./jobsparser
```

## Usage

```bash
.venv/bin/jobsparser \
  --search-term '("retail" OR "sales associate" OR cashier)' \
  --location "Portland, OR" \
  --distance 10 \
  --site indeed \
  --results-wanted 600 \
  --batch-size 100 \
  --sleep-time 60 \
  --hours-old 24 \
  --indeed-country US \
  --output-dir data
```

Repeat `--search-term` for several queries. Results are deduplicated on `job_url` and the
CSV is rewritten after each search term, so a long run is not lost if a later term fails.
The process exits non-zero if any term failed, with partial results still written.

See the [repository README](https://github.com/jitumaatgit/jobsparser) for full
documentation, and [ADR-0001](../docs/adr/0001-adopt-upstream-jobspy.md) for why this
fork depends on upstream JobSpy rather than the older `jobspy2`.

MIT licensed.