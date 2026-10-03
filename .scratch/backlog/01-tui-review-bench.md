---
Status: ready-for-agent
Type: task
Created: 2026-10-03
Deferred: until the current job search settles
---

# TUI review bench over jobsparser CSVs

A terminal UI for triaging scraped job results. **Nice to have — not started.**

## Why this exists

The scraper works and runs unattended for ~1h. The bottleneck is what happens after:
dedupe in Google Sheets, then the hand-maintained *title filter* column used to kill
false positives, then batch triage by **job family** (see `CONTEXT.md`).

From the archived notes (`~/notes/docs/90-archives/04-finding-employment-project/`):
*"I can't afford for good jobs to fall through the cracks"* — recall is preferred over
precision, so false positives are filtered by hand and a missed job cannot be recovered.

**A TUI around the scrape would be a nicer way to watch something that already runs
unattended.** That is not worth building. The review pass is the target.

## Proposed shape

```
┌──────────────────────────────────────────────────┐
│  JOBSCOUT  —  review bench over jobsparser CSVs   │
├──────────────────────────────────────────────────┤
│  1. LOADER    read data/jobs_*.csv → rows        │
│     dedupe by job_url · show provenance columns   │
├──────────────────────────────────────────────────┤
│  2. FILTER    / text search over title+company    │
│     saved rules per job family · age cutoff      │
├──────────────────────────────────────────────────┤
│  3. REVIEW    list ↔ detail panes                 │
│     j/k move · enter open · v open in browser     │
│     space = keep/reject · d = dismiss             │
├──────────────────────────────────────────────────┤
│  4. EXPORT    survivors → CSV                    │
└──────────────────────────────────────────────────┘
```

## Decisions already made

- **No new scraping code.** The TUI reads the CSVs the CLI already writes.
- **Textual** for widgets and key handling, `rich` for tables and markdown descriptions.
  Verified available: `textual 8.2.8`, requires Python >=3.9,<4.0, pulls `rich >=14.2.0`.
  Fits this project's Python 3.12.
- **Terminology comes from `CONTEXT.md`** — search term, job family, result set, false
  positive, pipeline. Do not invent new names.

## Open questions (unanswered — decide when picking this up)

1. **Output:** survivors CSV (keeps the Apps Script working unchanged) vs. write straight
   to Google Sheets via API (replaces the Apps Script, needs OAuth) vs. a local SQLite
   store (keep/reject decisions survive across sessions and re-runs).
2. **Scrape trigger:** out of scope for a review bench. Could be added later to run the
   existing CLI in the background.

## Known constraint when this was sketched

The session it was drafted in had `TERM=dumb`, so a TUI could be written but **not
visually verified as rendering**. Whoever builds this should confirm it renders on a
real terminal early, before building further on top of it.

## Why deferred

Raised on 2026-10-03 while finishing the Monday scrape goal. The CLI works; the review
pass is a Sheets workflow that has not proven painful enough to replace yet. Revisit if
the manual filtering step starts costing real time.