# jobsparser (personal fork)

A personal job-search CLI: scrapes **Indeed** for hand-written boolean search queries
and writes CSV that the review bench triages into applications. The Google Sheets
review pipeline this fork once fed is gone — see
[ADR-0002](docs/adr/0002-replace-sheets-review-pipeline.md).

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
`date_posted`, `job_url`, `description`, `search_term` and `term_label`.

`--term-label` records which job family each row came from. It takes one label per
search term, paired by position, so the terms stay self-describing in the CSV instead of
having to be reconstructed later:

```bash
.venv/bin/jobsparser \
  --search-term '("retail" OR cashier)' --term-label 'Retail, Logistics & Specialized Trades' \
  --search-term '("help desk" OR "data entry")' --term-label 'IT, Office & Documentation' \
  --location "Portland, OR" \
  --results-wanted 600 --output-dir data
```

Omitting it is fine: every row gets `term_label` of `''`. Giving a different number of
labels than search terms is a usage error, so a mis-paired run cannot half-complete.

Useful flags: `-v` for debug logging, `--max-retries` (default 3), `--proxies`,
`--remote/--no-remote`, `--job-type`.

## Querying the results

`jobsview.py` loads every `data/jobs_*.csv` into a single SQLite file with a
full-text index, so results can be filtered and searched without a spreadsheet
(stdlib only, no install):

```bash
python3 jobsview.py ingest          # build data/jobs.db from all run files
python3 jobsview.py stats           # coverage + employer concentration
python3 jobsview.py new --limit 20  # only jobs from the newest scrape
python3 jobsview.py search --match '"entry level" NOT CDL' --min-hourly 20
python3 jobsview.py search --company Nike --remote --sort salary
```

`--min-hourly` / `--min-annual` use the salary stated in the listing where
present, otherwise figures parsed out of the description (coverage rises from
about 47% to 62%). Queries combine: `--match` (FTS5 over title/company/
description), `--company`, `--location`, `--job-type`, `--remote`/`--onsite`,
`--since`, `--run`, `--sort`, `--limit`, `--urls`.

### Browse in Datasette

Install the optional viewer once, then index the CSVs and start a local-only
Datasette server:

```bash
make viewer-setup
make view
```

Open <http://127.0.0.1:8001/jobs/jobs>. `make view` rebuilds `data/jobs.db`
before serving it; stop the server with `Ctrl-C`.

### Browse in Neovim

For an in-editor SQLite browser, use [vim-dadbod](https://github.com/tpope/vim-dadbod)
and [vim-dadbod-ui](https://github.com/kristijanhusak/vim-dadbod-ui). After
installing them with your Neovim plugin manager, build/update the index and
launch Neovim with the database connection:

```bash
make index
DBUI_URL="sqlite:$PWD/data/jobs.db" nvim
```

Run `:DBUI`, open the `jobs` table, or write a SQL query buffer. For example,
the `jobs_fts` table supports full-text filtering:

```sql
SELECT title, company, location, date_posted, job_url
FROM jobs
WHERE rowid IN (
  SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH '"entry level" NOT CDL'
)
ORDER BY date_posted DESC;
```

## Review bench

The review pass happens here, not in a spreadsheet. `jobsview review` is a
terminal UI: a queue of unreviewed rows on the left, the description and
provenance on the right.

**The two axes.** Every row carries two independent verdicts:

- *Review decision* — `unreviewed` / `keep` / `false_positive` (is this job
  worth applying to at all?).
- *Application status* — `none` / `applied` / `interview` / `offer` /
  `rejected` / `withdrawn` (where an application to a kept job stands).

`space` cycles the decision, `y`/`x` set keep/false-positive directly, and one
key per application status (`a` applied, `i` interview, `o` offer, `r` rejected,
`w` withdrawn, `0`/`n` none). They are orthogonal: a false positive is a row
never worth applying to; `rejected` is an employer declining an application.

### Setup

```bash
make bench-setup          # installs Textual
.venv/bin/python jobsview.py review
```

`jobsview review` builds `data/jobs.db` first when the CSVs are newer, and
always reads and writes decisions in `data/review.db` (the only source of
truth for user state — never delete it).

### Keys

- `j`/`k` (or up/down) move; `enter` toggles focus between the list and the
  detail pane; `Ctrl+J`/`Ctrl+K` scroll the details.
- left/right scroll the queue when the terminal is too narrow for every column.
- `v` opens the job in a browser.
- `e` runs `jobsview export`, writing `data/survivors.csv` (every kept row,
  newest first) — the TUI and the CLI share one code path.
- `Ctrl-Z` undoes the last action; `q` quits (Escape no longer quits).
- After any action the cursor advances to the next row.

### Narrowing the queue

`/` opens a search bar over title and company (the same match `jobsview search
--match` makes, minus FTS and the description), `f` cycles the job-family
filter, `d` cycles the decision filter (`unreviewed` → `keep` →
`false_positive` → all), and `Escape` clears them all. Filters combine as a
conjunction, never re-query SQLite, and keep the queue's order; the header shows
every active filter.

`jobsview review --list` prints the same queue as one line per job, joined with
the store, for a headless check.

### Survivors export

`jobsview export` writes `data/survivors.csv` — a full snapshot of every kept row
in the shape the resume-synthesis step reads (12 columns: `job_url_direct`,
`title`, `company`, `date_posted`, `min_amount`, `max_amount`, `description`,
`search_term`, `term_label`, `job_family_source`, `decision`,
`application_status`). The first seven match `filter_job.py`'s output and order.
Overwrites on every run; an empty result writes a header-only file.

### Kanban export

`jobsview kanban` overwrites the kanban.nvim board at
`~/notes/docs/90-archives/04-finding-employment-project/application-process/kanban.md`
(one-way, by deliberate choice) with one card per kept row, grouped by
application status. False positives and unreviewed rows are absent.

**Migration gate:** the board's hand-added `gardencenter` card (and any other
card not in the bench) is destroyed by this export. Re-enter such cards in the
bench first, or accept the loss. No code papers over it.

### SQL escape hatch

Both stay available as an optional SQL escape hatch:

```bash
make viewer-setup
make view
```

and, for an in-editor SQLite browser, [vim-dadbod](https://github.com/tpope/vim-dadbod)
and [vim-dadbod-ui](https://github.com/kristijanhusak/vim-dadbod-ui) (`make index`,
then `DBUI_URL="sqlite:$PWD/data/jobs.db" nvim`).

## Notes

- Keep `--sleep-time` non-trivial. Bumping it too fast gets you rate-limited.
- Queries are deliberately broad — recall matters more than precision, since false
  positives are filtered by hand afterwards and a missed job cannot be recovered.
- JobSpy is consumed from git, so breaking upstream changes can reach you. Pin if that
  becomes a problem.


## Kanban export

`jobsview kanban` overwrites the kanban.nvim board at
`~/notes/docs/90-archives/04-finding-employment-project/application-process/kanban.md`
(one-way, by deliberate choice) with one card per kept row, grouped by
application status (`none` → `## Interested`, `applied` → `## Applied`,
`interview` → `## Interview`, `offer` → `## Offer`, `rejected` → `## Rejection`,
`withdrawn` → `## Withdrawn`). False positives and unreviewed rows are absent.

**Migration gate:** the board's hand-added `gardencenter` card (and any other card
not in the bench) is destroyed by this export. Re-enter such cards in the bench
before running it — or accept the loss. No code papers over it.

## License

MIT, inherited from the original.
