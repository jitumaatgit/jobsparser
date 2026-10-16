# Context

Glossary for this project. Terms are used consistently in code, docs, and issue text.

## Purpose:

A personal job-search tool. It scrapes Indeed for a hand-maintained set of boolean
search queries, writes CSV, and reviews those results in the review bench before
applications are written.

It is **not** a maintained public package, and not a general-purpose scraping library.

## Terms:

**Search term** — A boolean query written by hand, grouping job titles relevant to one
job family (for example retail/logistics, IT/office, social services/housing). The
query corpus is the real asset of this project; the scraper is commodity work.
One search term is one `--search-term` flag. Not to be confused with a single job title.

**Job family** — A group of related occupations that share one search term, named by a
header comment in `queries.txt` and stamped on each row as its `term_label`. It labels a
row and filters the review queue; it is not the unit of review, which is one row.
_Avoid_: query family, search group

**Provenance** — The record of which search term produced a row: the verbatim
`search_term` and its `term_label`. Rows scraped before provenance existed carry a
family guessed at review time, marked `job_family_source: inferred` — display-only, never
the basis of an exclusion rule.
_Avoid_: source, origin

**Scrape** — One run of the CLI for one search term at one location, producing one CSV.
A scrape is rate-limited by `--sleep-time` and `--batch-size`; it is not a bulk operation.

**Batch** — One network request inside a scrape. `--results-wanted` is fetched in
`--batch-size` chunks, sleeping `--sleep-time` seconds between them.

**Result set** — The deduplicated CSV rows from a scrape, keyed on job URL. Dedup happens
across batches and search terms within a run.

**False positive** — A row whose title matched the query but is not a job worth applying
to. Marked `false_positive` on the review decision in the review bench, never by the
scraper. Missing a good job is worse than an extra row — recall is preferred over
precision, so queries are deliberately broad.

**Review decision** — The verdict on whether a result is worth applying to:
`unreviewed`, `keep`, or `false_positive`. A `keep` verdict makes the row a survivor.
Orthogonal to application status.
_Avoid_: filter result, verdict, triage state

**Application status** — How far an application to a survivor has gone: `none`, `applied`,
`interview`, `offer`, `rejected`, or `withdrawn`. `rejected` means the employer declined —
not to be confused with a false positive, which is a row never worth applying to.
Orthogonal to the review decision.

**Survivor** — A row whose review decision is `keep`. The unit the review bench exports
and applications are written for.

**Review bench** — The in-repo terminal UI (`jobsview review`) where review decisions and
application statuses are set. It replaced the Google Sheets title filter.
_Avoid_: viewer, browser, dashboard

**Pipeline** — CSV → `jobs.db` → review bench → survivors CSV + kanban board →
applications. Owned inside this repo; the scraper's responsibility ends at writing CSV.
The Google Sheets pipeline it replaced (CSV → Sheets → Apps Script dedupe → manual title
filtering) is no longer part of this project.

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
- **Rejection** for a row never worth applying to — that is a *false positive*. Rejection
  is reserved for the employer declining an application.
- **Triage** as a synonym for a review decision — the review decision is one value
  (`unreviewed` / `keep` / `false_positive`), not the whole pass.
