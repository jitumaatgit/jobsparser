# jobsparser-fork — Salvage Assessment

**Date:** 2026-10-02
**Scope:** read-only investigation. No network requests were made against LinkedIn, Indeed, Glassdoor, ZipRecruiter, or Google.
**Provenance:** produced by a `scout` subagent during `/grill-with-docs`; key claims independently re-verified by the orchestrating agent.

---

## Verdict

**Hybrid: keep the CLI and the domain models, rewrite every scraper adapter — and Especially Indeed, the only site actually in use.**

The repo has a genuinely clean outer seam and a rotten core. The seam is worth keeping; the adapters are not salvageable as written.

---

## Architecture: clean outside, leaky inside

`jobsparser/` (CLI, click) imports exactly two names from the library — `scrape_jobs` and `LinkedInExperienceLevel` (`jobsparser/src/jobsparser/cli.py:2`). Site names are strings validated against `click.Choice(['linkedin','indeed','glassdoor','zip_recruiter','google'])` (`cli.py:131`), mapping 1:1 onto the `Site` enum (`jobspy2/src/jobspy2/scrapers/__init__.py:18-22`) and the `SCRAPER_MAPPING` dispatch dict (`jobspy2/src/jobspy2/__init__.py:140-146`). All CLI concerns — batching, retry/backoff, per-site threaded logging, CSV naming, `job_url` dedup — live only in `cli.py`.

Inside `jobspy2` the seam is nominal:

- `Scraper` ABC has one method, `scrape(ScraperInput) -> JobResponse` (`scrapers/__init__.py:62-70`), but `ScraperInput` is a 15-field god-model carrying `site_type: list[Site]` plus LinkedIn-only, Google-only and shared fields (`scrapers/__init__.py:39-59`).
- The **same mutable instance** is handed to all adapters concurrently (`__init__.py:152-170,176,182-186`) while `glassdoor:75` and `google:60` mutate `scraper_input.results_wanted`. Real race condition.
- Three incompatible transports hide underneath: HTML + BeautifulSoup (linkedin, ziprecruiter), private JSON/GraphQL APIs (indeed, glassdoor), and regex over raw HTML (google).
- `glassdoor:252` bypasses its own session with a bare module-level `requests.post`, silently discarding proxy rotation and TLS spoofing.

---

## Keep

| Path | Why |
|---|---|
| `jobsparser/src/jobsparser/cli.py` | Orchestration only; no scraping knowledge. The single highest-value file for this project's actual goal. |
| `jobspy2/src/jobspy2/jobs/__init__.py` | Domain models — `JobPost` (236-270), `Location.display_location` (183-202), `Country` incl. internal `WORLDWIDE`/`US_CANADA` (140-143), `CompensationInterval.get_interval` (212-221). Pure, no I/O. |
| `jobspy2/src/jobspy2/__init__.py` | Dispatch + dataframe shaping. Mutates nothing here. |
| `jobspy2/src/jobspy2/scrapers/__init__.py` | `Site` enum, `SalarySource`, `LinkedInExperienceLevel`, `Scraper` ABC. Shape is right; the *input model* is the leak. |

## Rewrite

| Path | Evidence |
|---|---|
| `scrapers/linkedin/__init__.py` | 13 hardcoded LinkedIn CSS hash classes (181,187,212,228,231,238,241,288,300,352,421). Bare debug `print(` at 126 sitting above the real logger at 128. `salary_values[1]` unguarded at 219. Chrome/120 UA. |
| `scrapers/indeed/__init__.py` | **Load-bearing.** Hardcoded private `indeed-api-key` on a 2024 iOS app build (`constants.py:103`, app v193.1 / iOS 16.6.1). 98-line hand-maintained GraphQL document (`constants.py:1-98`). Debug header/payload dump left in (117-124). Dead: `num_workers` (55), `_get_compensation_interval` (309), `_parse_compensation_interval` (326). |
| `scrapers/google/__init__.py` | Scrapes Google magic key `"520084652"` (228), regex over raw HTML (243), positional `job_info[28]`/`[19]`/`[3][0][0]` with no shape validation (190,208,211), ~4KB base64 token (`constants.py:52`). |
| `scrapers/glassdoor/__init__.py` | **Already dead** — see below. Also mutates shared `scraper_input` at 75. |
| `scrapers/ziprecruiter/__init__.py` | Hardcoded base64 Basic app credential (`constants.py:8`), device fingerprint (4-6), 2024 iPhone cookie blob (221). `test_all.py:10` says it "needs good ip". |
| `scrapers/utils.py` | Salary extraction (185-291) explicitly untested per TODO at 195. TLS/proxy sessions (32-132) depend on abandoned `tls-client`. numpy used only for `np.round` (176). `setup_logger` (309) dead. |

---

## Smoking gun: Glassdoor is already blocked

`log.html` at the repo root is a **captured Glassdoor bot-block interstitial** — `<title>Security | Glassdoor</title>`, brand green `#0caa41`. Independently re-verified. This is a debugging dump of a failed scrape, committed to the repo. Glassdoor is not "possibly broken" — someone already proved it broken and left the evidence in version control.

---

## Tests prove nothing

Six tests in `jobspy2/tests/`, **all live-network**, none skipped/xfailed/mocked, with exact row-count assertions (`== 5`). `test_all.py:10` comments out two sites with the comment *"ziprecruiter/linkedin needs good ip, and temp fix to pass test on ci"*. The suite cannot run in any sandboxed CI and cannot run at all without a residential IP.

---

## Dependencies

- `jobspy2`: hatchling, `requires-python >=3.9,<4.0` — inconsistent with the consumer's `>=3.10`. `numpy==1.26.3` hard pin for a single `np.round`. `tls-client>=1.0.1` — **abandoned**, 41MB. `markdownify>=0.13.1` resolved to 1.1.0.
- `jobsparser`: depends on `jobspy2` as an editable path dep (`pyproject.toml:31-32`).
- **Lockfile is stale**: `uv.lock:150` says jobspy2 0.0.7, `pyproject.toml` says 0.0.8.
- **No CI.** No `.github/` directory. Release is manual `uv publish` gated on `UV_PUBLISH_TOKEN` (`Makefile:22-34`, `.env.example:2`).

---

## Hygiene: safe to delete

| Path | Reason |
|---|---|
| `log.html` | Captured Glassdoor block page. Evidence, now read. |
| `.DS_Store`, `jobsparser/.DS_Store` | Committed macOS metadata. |
| `.cursor/rules/general.mdc` | Personal Cursor persona rules, `alwaysApply:true`, incl. "No need to disclose you're an AI" (23). Zero runtime value. |
| `jobspy2/README.md` | 100% untouched cookiecutter-uv boilerplate — instructs the reader to `git init -b main` (27) and badges a non-existent Actions workflow (4). Sole claimed feature is ~10 lines. |
| `jobsparser/src/jobsparser/cmds.txt` | Author's **private** LinkedIn exclusion list (33,46). Also stale: `mid_senior` (29) vs. actual enum value `mid_senior_level` — that command fails Click validation. |

`run_local.sh` — author's local dev helper; inspect before deleting.

---

## Contradiction in our own scaffolding

`AGENTS.md:5` says "no git remote yet" but `.git/refs/remotes/greeen-tea/` exists. `docs/agents/domain.md:7-9` points at `CONTEXT.md` and `docs/adr/`, neither of which exists. Both were written before the vendor step.