# jobsparser (personal fork)

A personal job-search CLI: scrapes **Indeed** for hand-written boolean search queries
and writes CSV for a Google Sheets review pipeline.

This is a fork of [FranciscoMoretti/jobsparser](https://github.com/FranciscoMoretti/jobsparser),
narrowed to one site and pointed at a maintained scraping library. See
[ADR-0001](docs/adr/0001-adopt-upstream-jobspy.md) for why, and
[CONTEXT.md](CONTEXT.md) for terminology.

## What changed from the original

- **Indeed only.** `--site` accepts `indeed` and nothing else. The LinkedIn, Glassdoor,
  ZipRecruiter and Google adapters are gone.
- **Scraping comes from [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy)**,
  which is actively maintained. This repo no longer contains a scraper.
- The CLI's batching, retry/backoff, threading, CSV output and URL dedup are unchanged.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e ./jobsparser
```

This pulls JobSpy from git — `jobsparser` depends on `python-jobspy @ git+https://github.com/speedyapply/JobSpy.git`.

## Use

```bash
.venv/bin/jobsparser \
  --search-term '("retail" OR "sales associate" OR cashier OR merchandiser)' \
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

Repeat `--search-term` to run several queries. Each run writes `data/jobs_<N>.csv`,
deduplicated on `job_url`. Columns include `title`, `company`, `location`,
`date_posted`, `job_url` and `description`.

Useful flags: `-v` for debug logging, `--max-retries` (default 3), `--proxies`,
`--remote/--no-remote`, `--job-type`.

## Notes

- Keep `--sleep-time` non-trivial. Bumping it too fast gets you rate-limited.
- Queries are deliberately broad — recall matters more than precision, since false
  positives are filtered by hand afterwards and a missed job cannot be recovered.
- JobSpy is consumed from git, so breaking upstream changes can reach you. Pin if that
  becomes a problem.

## License

MIT, inherited from the original.