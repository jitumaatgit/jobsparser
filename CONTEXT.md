# Context

Glossary for this project. Terms are used consistently in code, docs, and issue text.

## Purpose

A personal job-search tool. It scrapes Indeed for a hand-maintained set of boolean
search queries, writes CSV, and feeds a Google Sheets pipeline that dedupes and filters
results before applications are written.

It is **not** a maintained public package, and not a general-purpose scraping library.

## Terms

**Search term** — A boolean query written by hand, grouping job titles relevant to one
job family (for example retail/logistics, IT/office, social services/housing). The
query corpus is the real asset of this project; the scraper is commodity work.
One search term is one `--search-term` flag. Not to be confused with a single job title.

**Job family** — A group of related occupations that share one search term and are
reviewed together. The unit of how results are triaged.

**Scrape** — One run of the CLI for one search term at one location, producing one CSV.
A scrape is rate-limited by `--sleep-time` and `--batch-size`; it is not a bulk operation.

**Batch** — One network request inside a scrape. `--results-wanted` is fetched in
`--batch-size` chunks, sleeping `--sleep-time` seconds between them.

**Result set** — The deduplicated CSV rows from a scrape, keyed on job URL. Dedup happens
across batches and search terms within a run.

**False positive** — A row whose title matched the query but is not a job worth applying
to. These are removed manually in the Sheets pipeline via a title-filter column, not by
the scraper. Missing a good job is worse than an extra row — recall is preferred over
precision, so queries are deliberately broad.

**Pipeline** — CSV → Google Sheets → Apps Script dedupe → manual title filtering →
applications. Owned outside this repo; the scraper's responsibility ends at writing CSV.

**The fork** — This repository: the CLI only, scraping Indeed only. Distinct from
FranciscoMoretti/jobsparser (the original, unmaintained) and greeen-tea/jobsparser
(a lightly-modified fork of it). See ADR-0001.

**Upstream JobSpy** — `speedyapply/JobSpy` (distributed as `python-jobspy`), the actively
maintained scraping library this fork consumes. Not to be confused with the fork.

## Vocabulary deliberately avoided

- **Scraper** when referring to the library — that is *Upstream JobSpy*, an external
  dependency, not code in this repo.
- **Job posting** for a single row — use **result** or **row**.
- **Site** as a plural capability — this fork supports Indeed only.