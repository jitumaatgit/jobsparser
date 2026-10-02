---
status: accepted
date: 2026-10-02
---

# Adopt upstream JobSpy; keep only the CLI and scrape Indeed

This fork originally vendored `jobspy2` — a fork of `Bunsly/JobSpy` — as its scraping
library. We deleted it and now depend on `speedyapply/JobSpy` (distributed as
`python-jobspy`) directly, keeping only the CLI: batching, retry/backoff, threaded
per-search-term execution, CSV output, and URL dedup.

**Why.** `jobspy2` had been unmaintained since 2025-05-25 while its own upstream moved
daily. It carried a hardcoded 2024-era Indeed API key, 13 hardcoded LinkedIn CSS classes,
a committed Glassdoor bot-block page as proof that scraper was already dead, a
dependency on the abandoned `tls-client`, a `numpy` pin for a single `np.round`, and a
live race condition from handing one mutable `ScraperInput` to concurrent adapters. Its
6 tests were all live-network with no mocks — `test_all.py` commented out two sites with
"temp fix to pass test on ci". Repairing that was a rewrite wearing a maintenance
commitment. Upstream JobSpy is more alive than the thing we would have been maintaining,
and uses the same Indeed API key.

**Scope.** Indeed only. `--site` is restricted to Indeed and the LinkedIn-specific
options (`--fetch-description`, `--linkedin-experience-level`) are removed rather than
stubbed. We never scrape LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google, or any other
site; the vendored Glassdoor scraper was already blocked, and maintaining five adapters
is the fragility this decision exists to remove.

**Considered.** Keeping `jobspy2` and repairing its Indeed adapter — rejected, because it
commits to maintaining a fork whose upstream is strictly better. Continuing to track
`greeen-tea/jobsparser` as upstream — rejected; it adds ~6 lines of real code (a
`--remote` flag and a debug print) over the original and is itself unmaintained.

**Consequences.** We now inherit upstream's breaking changes and must track its
dependency graph rather than controlling it. In exchange we receive working scrapers
whenever Indeed changes. `hatch.metadata.allow-direct-references` is enabled because
hatchling rejects git dependencies otherwise, and the distribution name is
`python-jobspy` even though the import is `jobspy`.