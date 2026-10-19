#!/usr/bin/env python3
"""jobsview -- a query layer over the jobsparser CSV output.

The CSV is effectively write-only: fine to hand to a spreadsheet once, but it
cannot answer the questions a job search actually asks -- "what is new since
yesterday", "any entry-level role that does not mention a CDL", "what pays at
least $20/hr".  This loads every ``data/jobs_*.csv`` into one SQLite file with a
full-text index and answers those from the command line.

Standard library only; no install step.

    python3 jobsview.py ingest
    python3 jobsview.py review --list
    python3 jobsview.py stats
    python3 jobsview.py new --limit 20
    python3 jobsview.py search --match '"entry level" NOT CDL' --min-hourly 20
    python3 jobsview.py search --company Nike --remote
    python3 jobsview.py search --min-annual 60000 --sort salary
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN_RE = re.compile(r"jobs_(\d+)\.csv$")

# "$18 - $22 /hr", "$18-$22 per hour"
_HOURLY_RANGE = re.compile(
    r"\$\s*(\d{1,3}(?:\.\d{1,2})?)\s*(?:-|\u2013|\u2014|to)\s*\$?\s*(\d{1,3}(?:\.\d{1,2})?)"
    r"\s*(?:/|per\s+)\s*(?:hr|hour|hourly)\b",
    re.I,
)
_HOURLY_ONE = re.compile(r"\$\s*(\d{1,3}(?:\.\d{1,2})?)\s*(?:/|per\s+)\s*(?:hr|hour|hourly)\b", re.I)
_ANNUAL_RANGE = re.compile(
    r"\$\s*(\d{2,3}(?:,\d{3})+)\s*(?:-|\u2013|\u2014|to)\s*\$?\s*(\d{2,3}(?:,\d{3})+)",
)
_ANNUAL_ONE = re.compile(r"\$\s*(\d{2,3}(?:,\d{3})+)")

DERIVED = [
    ("first_run", "INTEGER"),
    ("last_run", "INTEGER"),
    ("hourly_min", "REAL"),
    ("hourly_max", "REAL"),
    ("annual_min", "REAL"),
    ("annual_max", "REAL"),
    ("job_family", "TEXT"),
    ("job_family_source", "TEXT"),
]


def _f(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _money(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_pay_text(text: str):
    """Best-effort hourly/annual figures from a job description body."""
    if not text:
        return None, None, None, None
    m = _HOURLY_RANGE.search(text)
    if m:
        return float(m.group(1)), float(m.group(2)), None, None
    m = _HOURLY_ONE.search(text)
    if m:
        v = float(m.group(1))
        return v, v, None, None
    m = _ANNUAL_RANGE.search(text)
    if m:
        return None, None, _money(m.group(1)), _money(m.group(2))
    m = _ANNUAL_ONE.search(text)
    if m:
        v = _money(m.group(1))
        return None, None, v, v
    return None, None, None, None


def derive_pay(row: dict):
    interval = (row.get("interval") or "").strip().lower()
    mn, mx = _f(row.get("min_amount")), _f(row.get("max_amount"))
    hmin = hmax = amin = amax = None
    if interval == "hourly":
        hmin, hmax = mn, mx
    elif interval in ("yearly", "annual", "annually"):
        amin, amax = mn, mx
    if hmin is None and amin is None:
        hmin, hmax, amin, amax = parse_pay_text(row.get("description") or "")
    return hmin, hmax, amin, amax


def _run_files(data_dir: Path):
    def idx(p: Path) -> int:
        m = RUN_RE.search(p.name)
        return int(m.group(1)) if m else -1

    return sorted(
        (p for p in data_dir.glob("jobs_*.csv") if RUN_RE.search(p.name)),
        key=idx,
    )


# -- family map (queries.txt) -----------------------------------------------
#
# queries.txt is the single file a human edits: a "# --- <Family> ---" header
# names the job family of every search term under it (CONTEXT.md), and
# run_queries.sh walks the same rule to stamp --term-label. Parsing the map
# here from the same file keeps that one source of truth. Two projections of
# the file are needed: the whole term, which is what lands in a CSV's
# search_term column, and the phrases inside it, which is the only thing a
# legacy row can be matched against.
_OR_SPLIT = re.compile(r"\s+OR\s+", re.I)
_TRIM = " \t\"'()"
_HEADER_PREFIX = "# --- "
_HEADER_SUFFIX = " ---"


def _norm(text: str) -> str:
    """Collapse a term's whitespace so a CSV value and a queries.txt line
    compare equal even when one of them carries extra spaces."""
    return " ".join((text or "").split())


def _query_pairs(path: Path) -> list[tuple[str, str]]:
    """[(search term, job family)] straight from queries.txt's headers."""
    pairs: list[tuple[str, str]] = []
    family = ""
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        trimmed = line.strip()
        if trimmed.startswith(_HEADER_PREFIX) and trimmed.endswith(_HEADER_SUFFIX):
            family = trimmed[len(_HEADER_PREFIX):-len(_HEADER_SUFFIX)].strip()
        elif trimmed and not trimmed.startswith("#") and family:
            pairs.append((_norm(trimmed), family))
    return pairs


def parse_family_map(path) -> dict[str, str]:
    """Each search term in queries.txt mapped to the family header above it.

    A term above every header is absent from the map rather than mapped to
    nothing, so such a row falls back to the title guess and is only (unknown)
    when that misses too.
    """
    return {term: family for term, family in _query_pairs(path)}


def _search_phrases(term: str) -> list[str]:
    """The individual phrases inside one OR-group search term."""
    phrases = [a.strip(_TRIM).strip() for a in _OR_SPLIT.split(term.strip())]
    return [p for p in phrases if p]


def family_terms(path) -> dict[str, list[str]]:
    """Each family's search phrases, in queries.txt order.

    That order is what breaks ties in guess_family, so it is insertion order
    rather than sorted -- a guess has to stay reproducible.
    """
    out: dict[str, list[str]] = {}
    for term, family in _query_pairs(path):
        out.setdefault(family, []).extend(_search_phrases(term))
    return out


def guess_family(title: str, terms_by_family: dict[str, list[str]]) -> str | None:
    """Guess one row's job family from its title. Display-only by definition.

    Case-insensitive substring match, and the longest matching phrase wins so
    the specific family claims the row -- "sales associate" outranks "sales".
    This heuristic is the whole reason it is one small function: the legacy
    backfill is a guess that will need re-tuning.
    """
    hay = _norm(title).lower()
    if not hay:
        return None
    best: tuple[int, str] | None = None
    for family, phrases in terms_by_family.items():
        for phrase in phrases:
            needle = _norm(phrase).lower()
            if needle in hay and (best is None or len(needle) > best[0]):
                best = (len(needle), family)
    return best[1] if best else None


def resolve_family(row: dict, family_map: dict[str, str],
                   terms_by_family: dict[str, list[str]]) -> tuple[str, str]:
    """(job family, job_family_source) for one scraped row.

    The source is what the bench's flag keys on:
      stamped  -- the CSV carried term_label, so the family is recorded fact
      inferred -- the CSV did not, so the family was recovered from
                  queries.txt, by exact term or guessed from the title.
                  Display-only: never the basis of an exclusion rule.
      unknown  -- neither, shown as (unknown) and never filtered out
    """
    label = (row.get("term_label") or "").strip()
    if label:
        return label, "stamped"
    family = family_map.get(_norm(row.get("search_term")))
    if family:
        return family, "inferred"
    guessed = guess_family(row.get("title") or "", terms_by_family)
    if guessed:
        return guessed, "inferred"
    return "(unknown)", "unknown"


def cmd_ingest(args) -> int:
    data_dir = Path(args.data_dir)
    files = _run_files(data_dir)
    if not files:
        print(f"no jobs_*.csv under {data_dir}", file=sys.stderr)
        return 1

    # The job family is derived here, in the derived index: every reader
    # (review --list, the bench, the exports) then gets it from one place, and
    # a re-tuned queries.txt is picked up by the next ingest.
    queries = Path(getattr(args, "queries", None) or "queries.txt")
    try:
        if queries.exists():
            family_map = parse_family_map(queries)
            terms_by_family = family_terms(queries)
        else:
            family_map, terms_by_family = {}, {}
            print(f"no family map at {queries} -- job families will be "
                  f"guessed from titles or (unknown)", file=sys.stderr)
    except (OSError, UnicodeDecodeError) as err:
        # The one file a human edits, so a half-saved or unreadable one
        # degrades the families instead of failing the whole ingest.
        family_map, terms_by_family = {}, {}
        print(f"cannot read the family map at {queries}: {err}", file=sys.stderr)

    rows: list[dict] = []
    seen: dict[str, int] = {}
    header: list[str] = []
    for run_no, path in ((RUN_RE.search(p.name).group(1), p) for p in files):
        run_no = int(run_no)
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            # Every run file's columns, first-seen order: a newer CSV adds
            # search_term/term_label that a legacy first CSV lacks, and a
            # first-header-only table would silently drop them.
            for col in reader.fieldnames or []:
                if col not in header:
                    header.append(col)
            for row in reader:
                url = (row.get("job_url") or "").strip()
                if not url:
                    continue
                if url in seen:
                    prior = rows[seen[url]]
                    prior["last_run"] = run_no
                    # First writer keeps the row, but a later run that carries
                    # the family label beats the guess backfilled for it:
                    # recorded fact over inference. A stamp already on the row
                    # stays put, so the first term to name a family keeps it.
                    family, source = resolve_family(row, family_map, terms_by_family)
                    if source == "stamped" and prior["job_family_source"] != "stamped":
                        prior["job_family"], prior["job_family_source"] = family, source
                    continue
                hmin, hmax, amin, amax = derive_pay(row)
                row["first_run"] = run_no
                row["last_run"] = run_no
                row["hourly_min"], row["hourly_max"] = hmin, hmax
                row["annual_min"], row["annual_max"] = amin, amax
                row["job_family"], row["job_family_source"] = resolve_family(
                    row, family_map, terms_by_family
                )
                seen[url] = len(rows)
                rows.append(row)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    cols_sql = ", ".join(f'"{c}" TEXT' for c in header)
    derived_sql = ", ".join(f'"{c}" {t}' for c, t in DERIVED)
    cur.execute(f"CREATE TABLE jobs (rowid INTEGER PRIMARY KEY, {cols_sql}, {derived_sql})")
    cur.execute("CREATE VIRTUAL TABLE jobs_fts USING fts5(title, company, description)")

    names = header + [c for c, _ in DERIVED]
    placeholders = ", ".join("?" * len(names))
    insert = f"INSERT INTO jobs (rowid, {', '.join('\"%s\"' % c for c in names)}) VALUES (?, {placeholders})"
    fts_insert = "INSERT INTO jobs_fts (rowid, title, company, description) VALUES (?, ?, ?, ?)"

    for i, row in enumerate(rows, start=1):
        cur.execute(insert, [i] + [row.get(c) for c in names])
        cur.execute(
            fts_insert,
            (i, row.get("title") or "", row.get("company") or "", row.get("description") or ""),
        )
    con.commit()
    n = len(rows)
    with_salary = sum(1 for r in rows if r["hourly_min"] is not None or r["annual_min"] is not None)
    print(f"ingested {n} unique jobs from {len(files)} run file(s) -> {db_path}")
    share = f" ({with_salary / n:.0%})" if n else ""  # a run file can hold no rows
    print(f"salary known for {with_salary}/{n}{share}")
    con.close()
    return 0

# -- review store (data/review.db) ------------------------------------------
#
# User-authored state: the review decision, the application status and the run
# numbers a row was seen in. Unlike jobs.db this file is never rebuilt or
# unlinked -- it is the only source of truth for decisions and applications.

# Deliberately no migration machinery: if these columns change, hand-edit or
# re-derive the file, which means the DDL below is effectively write-once. The
# CHECKs are therefore not redundant with the Python guard -- they are the one
# layer that cannot be added after a store exists, and they make conflating the
# two axes impossible at the storage layer too.
REVIEW_DDL = """
CREATE TABLE IF NOT EXISTS jobs_review (
    job_url            TEXT PRIMARY KEY,
    decision           TEXT NOT NULL DEFAULT 'unreviewed'
                      CHECK (decision IN ('unreviewed', 'keep', 'false_positive')),
    application_status TEXT NOT NULL DEFAULT 'none'
                      CHECK (application_status IN ('none', 'applied', 'interview',
                                                     'offer', 'rejected', 'withdrawn')),
    first_run          INTEGER,
    last_run           INTEGER,
    decided_at         TEXT,
    updated_at         TEXT
)
"""

# The two axes are orthogonal and their vocabularies must never be conflated:
# false_positive is a row never worth applying to, rejected is an employer
# declining an application (CONTEXT.md).
DECISIONS = ("unreviewed", "keep", "false_positive")
APPLICATION_STATUSES = ("none", "applied", "interview", "offer", "rejected", "withdrawn")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_axis(value: str, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise ValueError(f"unknown {what} {value!r}; expected one of {', '.join(allowed)}")
    return value


def _review_db(args) -> sqlite3.Connection:
    """Open the sidecar, creating it when it is missing.

    Creating it is safe on a read path; deleting it never is. The file sits
    beside the CSVs it describes rather than at --db, which names the derived
    jobs index that ingest rebuilds.
    """
    db = Path(args.data_dir) / "review.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(REVIEW_DDL)
    return con


def ensure_review_row(con, job_url: str, first_run=None, last_run=None) -> None:
    """Create the row for one job_url, or widen the run range it was seen in.

    Rows are never dropped: a result that stops appearing in newer CSVs keeps
    its decision, so this never touches decision, decided_at or
    application_status. `updated_at` moves only when the run range does --
    "timestamp of the last change" per spec, not of the last ingest pass.
    """
    with con:
        con.execute(
            "INSERT INTO jobs_review (job_url, first_run, last_run, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (job_url) DO UPDATE SET "
            "first_run = MIN(COALESCE(first_run, excluded.first_run), "
            "               COALESCE(excluded.first_run, first_run)), "
            "last_run = MAX(COALESCE(last_run, excluded.last_run), "
            "              COALESCE(excluded.last_run, last_run)), "
            "updated_at = CASE WHEN first_run IS excluded.first_run "
            "                   AND last_run IS excluded.last_run "
            "                THEN updated_at ELSE excluded.updated_at END",
            (job_url, first_run, last_run, _utcnow()),
        )


def set_decision(con, job_url: str, decision: str) -> None:
    """Set the review decision for one row. Leaves the application status alone.

    `decided_at` is the timestamp of the decision the row currently carries:
    unchanged while the verdict moves between two decided values, stamped when
    it first becomes decided, and cleared when it goes back to `unreviewed` --
    the undo case must not leave a timestamp behind.
    """
    _check_axis(decision, DECISIONS, "review decision")
    stamp = None if decision == "unreviewed" else _utcnow()
    with con:
        con.execute(
            "INSERT INTO jobs_review (job_url, decision, decided_at, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (job_url) DO UPDATE SET "
            "decision = excluded.decision, "
            "decided_at = CASE WHEN excluded.decided_at IS NULL THEN NULL "
            "                  ELSE COALESCE(jobs_review.decided_at, excluded.decided_at) END, "
            "updated_at = excluded.updated_at",
            (job_url, decision, stamp, _utcnow()),
        )


def set_application_status(con, job_url: str, application_status: str) -> None:
    """Move a survivor along the application axis. Leaves the decision alone."""
    _check_axis(application_status, APPLICATION_STATUSES, "application status")
    with con:
        con.execute(
            "INSERT INTO jobs_review (job_url, application_status, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT (job_url) DO UPDATE SET "
            "application_status = excluded.application_status, "
            "updated_at = excluded.updated_at",
            (job_url, application_status, _utcnow()),
        )


def _missing_index(db: Path) -> str:
    """The one message for a missing derived index, so it cannot drift."""
    return f"{db} missing -- run: python3 jobsview.py ingest"


def _index_is_stale(args) -> bool:
    """True when the derived jobs index is behind the CSVs or the family map.

    A newer run file is the obvious trigger; so is a newer queries.txt, because
    the job families are derived from it and that guess is meant to be re-tuned
    without a second command.
    """
    db = Path(args.db)
    if not db.exists():
        return True
    built = db.stat().st_mtime
    for newer in (p.stat().st_mtime for p in _run_files(Path(args.data_dir))):
        if newer > built:
            return True
    queries = Path(getattr(args, "queries", None) or "queries.txt")
    return queries.exists() and queries.stat().st_mtime > built


def _index_has_every_column(args) -> bool:
    """False when the derived index predates a column jobs.db is expected to
    carry, whatever its mtime says.

    An index built before the family map landed has no job_family column, and it
    would otherwise stay current forever: no CSV ever moves again, so an mtime
    check alone would keep serving a table the join cannot read.
    """
    db = Path(args.db)
    if not db.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            have = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return all(c in have for c, _ in DERIVED)


def cmd_review(args) -> int:
    csvs = _run_files(Path(args.data_dir))
    if not csvs and not Path(args.db).exists():
        print(_missing_index(Path(args.db)), file=sys.stderr)
        return 1
    if csvs and (_index_is_stale(args) or not _index_has_every_column(args)):
        # Ingesting here is safe precisely because the decisions live in the
        # sidecar: rebuilding the derived index cannot destroy them. An index
        # with no CSVs beside it is left alone rather than rebuilt empty.
        rc = cmd_ingest(args)
        if rc != 0:
            return rc
    if getattr(args, "list", False):
        return cmd_review_list(args)
    try:
        import textual  # noqa: F401 -- keep the optional dependency inside this command
        from jobsview_tui import ReviewBenchApp
    except ModuleNotFoundError as err:
        if err.name != "textual":
            raise
        print("Textual is not installed; run: make bench-setup", file=sys.stderr)
        return 1
    ReviewBenchApp(args).run()
    return 0


def _family_label(r) -> str:
    """The family as the bench shows it, with a guess flagged as one."""
    if r["job_family_source"] == "inferred":
        return f"{r['job_family'] or '(unknown)'} (inferred)"
    return r["job_family"] or "(unknown)"


def _review_rows(con, db_path):
    """Joined queue rows, including optional CSV details for the bench."""
    con.execute("ATTACH DATABASE ? AS jobs", (str(Path(db_path)),))
    con.row_factory = sqlite3.Row
    columns = {row[1] for row in con.execute("PRAGMA jobs.table_info(jobs)")}
    details = (
        "job_url_direct", "search_term", "term_label", "description",
        "min_amount", "max_amount",
    )
    optional = ", ".join(
        f"j.{column}" if column in columns else f"NULL AS {column}"
        for column in details
    )
    return con.execute(
        "SELECT j.job_url, j.title, j.company, j.location, j.date_posted, "
        "j.job_family, j.job_family_source, j.last_run, "
        "j.hourly_min, j.hourly_max, j.annual_min, j.annual_max, "
        "r.decision, r.application_status, " + optional + " "
        "FROM jobs.jobs j LEFT JOIN jobs_review r ON r.job_url = j.job_url "
        "ORDER BY j.rowid"
    ).fetchall()


def cmd_review_list(args) -> int:
    """One line per job, joined with the store, so the queue is readable
    without the TUI: title, company, location, date, pay, family, decision,
    application status, then the run the row was last seen in.

    jobs.db drives the listing, so a row that stops appearing in newer CSVs
    drops off the list while keeping its state in the sidecar; a job with no
    store row is unreviewed/none by default rather than written there by a read.
    The store is the connection's main schema so the review store's DDL lands
    in it, and the derived index is attached just for the join.
    """
    try:
        con = _review_db(args)
    except (OSError, sqlite3.Error) as err:
        db = Path(args.data_dir) / "review.db"
        print(f"cannot open {db}: {err}", file=sys.stderr)
        return 1
    try:
        rows = _review_rows(con, args.db)
    except sqlite3.Error as err:
        # Let sqlite's specific join or schema message through unchanged.
        print(f"cannot list the queue from {Path(args.db)}: {err}", file=sys.stderr)
        return 1
    finally:
        con.close()

    if not rows:
        print("(no jobs in the index)")
        return 0
    for r in rows:
        cells = [
            (r["title"] or "")[:46].ljust(46),
            (r["company"] or "")[:26].ljust(26),
            (r["location"] or "")[:20].ljust(20),
            (r["date_posted"] or "")[:10],
            f"{_pay_label(r):<18}",
            _family_label(r).ljust(46),
            (r["decision"] or "unreviewed").ljust(14),
            (r["application_status"] or "none").ljust(10),
            f"run {r['last_run']}",
            r["job_url"],
        ]
        print(" ".join(cells))
    return 0

# -- survivors export (data/survivors.csv) -----------------------------------
#
# The snapshot the resume-synthesis step reads. The first seven columns are
# filter_job.py's output, in its order, so prompts and scripts that already
# read ~/notes/.../interesting-jobs.csv keep working unchanged.
# `job_family_source` qualifies the provenance columns it follows (stamped /
# inferred / unknown), so a guessed family is never mistaken for a recorded
# one; `job_family` itself is not exported -- it is recoverable from
# search_term/term_label, and the synthesis step does not read it.

EXPORT_COLUMNS = (
    "job_url_direct", "title", "company", "date_posted",
    "min_amount", "max_amount", "description",
    "search_term", "term_label", "job_family_source",
    "decision", "application_status",
)


def _export_path(args) -> Path:
    """Where the snapshot is written, defaulting beside the sidecar store."""
    return Path(getattr(args, "output", None) or Path(args.data_dir) / "survivors.csv")


def export_survivors(args, output: Path) -> int:
    """Write every kept row to ``output``; return the count written.

    Only ``keep`` rows: a false positive is a row never worth applying to and
    an unreviewed row has not been judged yet, so neither belongs in a snapshot
    a resume step would read. The join is the queue's -- jobs.db drives, so a
    row that dropped out of newer CSVs is gone from the snapshot too while its
    decision stays in the sidecar.

    Newest first; ties keep the index's order (a stable reverse sort on a
    YYYY-MM-DD string is chronological). The file is rewritten in full every
    run via an atomic replace, so an interrupted export cannot leave a torn
    snapshot -- the file either reflects the last good run or the one before.
    An empty result still writes the header: the file must never lie about what
    it contains.
    """
    con = _review_db(args)
    try:
        rows = [
            dict(r) for r in _review_rows(con, Path(args.db))
            if (r["decision"] or "unreviewed") == "keep"
        ]
    finally:
        con.close()
    rows = sorted(rows, key=lambda r: r["date_posted"] or "", reverse=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(EXPORT_COLUMNS)
        for r in rows:
            writer.writerow([r.get(c) if r.get(c) is not None else "" for c in EXPORT_COLUMNS])
    tmp.replace(output)
    return len(rows)


def cmd_export(args) -> int:
    """Write the survivors snapshot the resume-synthesis step reads."""
    db = Path(args.db)
    if not db.exists():
        print(_missing_index(db), file=sys.stderr)
        return 1
    output = _export_path(args)
    try:
        count = export_survivors(args, output)
    except (OSError, sqlite3.Error) as err:
        print(f"cannot write {output}: {err}", file=sys.stderr)
        return 1
    print(f"{count} kept job(s) -> {output}")
    return 0


# -- kanban.md export --------------------------------------------------------
KANBAN_SECTIONS = (
    ("none", "Interested"),
    ("applied", "Applied"),
    ("interview", "Interview"),
    ("offer", "Offer"),
    ("rejected", "Rejection"),
    ("withdrawn", "Withdrawn"),
)
_STATUS_TO_SECTION = {status: name for status, name in KANBAN_SECTIONS}
def _kanban_path(args) -> Path:
    return Path(getattr(args, "kanban", None) or (Path.home() / "notes" / "docs" / "90-archives" / "04-finding-employment-project" / "application-process" / "kanban.md"))


def export_kanban(args, output: Path) -> int:
    """Write the board; return the number of cards written."""
    con = _review_db(args)
    try:
        rows = [dict(r) for r in _review_rows(con, Path(args.db))]
    finally:
        con.close()
    kept = [r for r in rows if (r["decision"] or "unreviewed") == "keep"]

    buckets: dict[str, list[dict]] = {name: [] for _, name in KANBAN_SECTIONS}
    for r in kept:
        status = r.get("application_status") or "none"
        section = _STATUS_TO_SECTION.get(status, "Interested")
        buckets[section].append(r)

    # Preserve the board's own frontmatter and settings blocks verbatim when
    # the file already exists. The Obsidian kanban plugin rewrites the
    # settings block with the user's board config (lane width, date format, …);
    # rebuilding it from a template would silently reset that. Fall back to the
    # canonical blocks only for a board that does not exist yet.
    front_block = "---\n\nkanban-plugin: basic\n\n---\n"
    settings_block = (
        "%% kanban:settings\n```\n{\"kanban-plugin\":\"basic\"}\n```\n%%"
    )
    if output.exists():
        try:
            existing = output.read_text(encoding="utf-8")
            head = existing.split("## ", 1)[0]
            # frontmatter is the leading `--- … ---` block
            fm_end = head.find("---", head.find("---") + 3)
            if fm_end != -1:
                fm = head[:fm_end + 3].strip()
                if fm.startswith("---"):
                    front_block = fm
            # settings block is the trailing `%% kanban:settings … %%`
            marker = "%% kanban:settings"
            idx = existing.rfind(marker)
            if idx != -1:
                tail = existing[idx:]
                end = tail.find("%%", len(marker))
                if end != -1:
                    settings_block = tail[:end + 2].rstrip()
        except OSError:
            pass

    lines = [front_block, ""]
    for _, name in KANBAN_SECTIONS:
        lines.append(f"## {name}")
        lines.append("")
        for r in buckets[name]:
            title = (r.get("title") or "").strip()
            company = (r.get("company") or "").strip()
            card = f"{title} — {company}".strip(" —")
            lines.append(f"- [ ] {card}")
        lines.append("")
    lines.append("")
    lines.append(settings_block)
    lines.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(output)
    return len(kept)



def cmd_kanban(args) -> int:
    db = Path(args.db)
    if not db.exists():
        print(_missing_index(db), file=sys.stderr)
        return 1
    output = _kanban_path(args)
    try:
        count = export_kanban(args, output)
    except (OSError, sqlite3.Error) as err:
        print(f"cannot write {output}: {err}", file=sys.stderr)
        return 1
    print(f"{count} card(s) -> {output}")
    return 0


def _open(args):
    db = Path(args.db)
    if not db.exists():
        print(_missing_index(db), file=sys.stderr)
        sys.exit(1)
    return sqlite3.connect(db)


def _pay_label(r) -> str:
    if r["hourly_max"] is not None:
        lo = r["hourly_min"] if r["hourly_min"] is not None else r["hourly_max"]
        return f"${lo:.0f}-{r['hourly_max']:.0f}/hr" if lo != r["hourly_max"] else f"${lo:.0f}/hr"
    if r["annual_max"] is not None:
        lo = r["annual_min"] if r["annual_min"] is not None else r["annual_max"]
        return f"${lo:,.0f}-{r['annual_max']:,.0f}/yr" if lo != r["annual_max"] else f"${lo:,.0f}/yr"
    return "-"


def _print(rows, urls_only: bool = False) -> None:
    if not rows:
        print("(no matches)")
        return
    for r in rows:
        if urls_only:
            print(r["job_url"])
            continue
        title = (r["title"] or "")[:46].ljust(46)
        company = (r["company"] or "")[:26].ljust(26)
        loc = (r["location"] or "")[:22].ljust(22)
        date = (r["date_posted"] or "")[:10]
        print(f"{title} {company} {loc} {date}  {_pay_label(r):<18} {r['job_url']}")


# -- the bench's search term -------------------------------------------------
#
# The review bench searches the rows it has already loaded -- re-querying
# SQLite per keystroke would rebuild a 300-row queue on every character. Its
# search is `jobsview search --match` minus FTS: the same title/company
# coverage, plain LIKE instead of the FTS5 index, and never the description.
# The pattern and the matcher are defined here, beside `_build_query`, so one
# term cannot mean one thing in the CLI and another in the TUI.
SEARCH_COLUMNS = ("title", "company")


def _like_pattern(value: str) -> str:
    """A user fragment as a LIKE pattern: where the `%` wrap happens."""
    return f"%{value}%"


def _like_matches(pattern: str, value: str) -> bool:
    """SQLite's LIKE for one pattern/value pair, in memory.

    ASCII case-insensitive with `%` and `_` wildcards: the semantics the CLI
    hands to SQLite, reproduced for a row that is already loaded.

    `re.ASCII` is load-bearing. Python's IGNORECASE folds all of Unicode, so
    without it a term matches a strict superset of the CLI's results -- "k"
    against U+212A (KELVIN SIGN) is True here and 0 in SQLite. Measured.
    """
    expression = "".join(
        ".*" if character == "%"
        else "." if character == "_"
        else re.escape(character)
        for character in pattern
    )
    return (
        re.match(expression, value, re.IGNORECASE | re.ASCII | re.DOTALL) is not None
    )


def matches_search(row, term: str) -> bool:
    """True when the row's title or company LIKE the search term."""
    if not term:
        return True
    pattern = _like_pattern(term)
    return any(
        _like_matches(pattern, row.get(column) or "") for column in SEARCH_COLUMNS
    )


def _build_query(args):
    where, params = [], []
    fts = False
    if getattr(args, "match", None):
        fts = True
        where.append("j.rowid IN (SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?)")
        params.append(args.match)
    if getattr(args, "company", None):
        where.append("j.company LIKE ?")
        params.append(_like_pattern(args.company))
    if getattr(args, "location", None):
        where.append("j.location LIKE ?")
        params.append(_like_pattern(args.location))
    if getattr(args, "job_type", None):
        where.append("j.job_type LIKE ?")
        params.append(_like_pattern(args.job_type))
    if getattr(args, "remote", False):
        where.append("j.is_remote IN ('True','true','1')")
    if getattr(args, "onsite", False):
        where.append("j.is_remote IN ('False','false','0')")
    if getattr(args, "min_hourly", None) is not None:
        where.append("j.hourly_max >= ?")
        params.append(args.min_hourly)
    if getattr(args, "min_annual", None) is not None:
        where.append("j.annual_max >= ?")
        params.append(args.min_annual)
    if getattr(args, "since", None):
        where.append("j.date_posted >= ?")
        params.append(args.since)
    if getattr(args, "new", False):
        where.append("j.first_run = (SELECT MAX(first_run) FROM jobs)")
    if getattr(args, "run", None) is not None:
        where.append("j.last_run >= ?")
        params.append(args.run)

    sort = {
        "date": "j.date_posted DESC",
        "salary": "COALESCE(j.annual_max, j.hourly_max) DESC NULLS LAST",
        "company": "j.company ASC",
        "title": "j.title ASC",
    }.get(getattr(args, "sort", "date"), "j.date_posted DESC")
    sql = "SELECT j.* FROM jobs j"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {sort} LIMIT ?"
    params.append(args.limit)
    return sql, params, fts


def _run_search(args, extra_note: str | None = None) -> int:
    con = _open(args)
    con.row_factory = sqlite3.Row
    sql, params, _ = _build_query(args)
    rows = con.execute(sql, params).fetchall()
    if extra_note:
        print(extra_note)
    _print(rows, urls_only=getattr(args, "urls", False))
    print(f"\n{len(rows)} row(s)")
    con.close()
    return 0


def cmd_search(args) -> int:
    return _run_search(args)


def cmd_new(args) -> int:
    args.new = True
    note = None
    con = _open(args)
    con.row_factory = sqlite3.Row
    latest = con.execute("SELECT MAX(first_run) AS m FROM jobs").fetchone()["m"]
    note = f"jobs first seen in run {latest} (newest scrape):"
    con.close()
    return _run_search(args, extra_note=note)


def cmd_stats(args) -> int:
    con = _open(args)
    con.row_factory = sqlite3.Row
    total = con.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
    with_pay = con.execute(
        "SELECT COUNT(*) c FROM jobs WHERE hourly_min IS NOT NULL OR annual_min IS NOT NULL"
    ).fetchone()["c"]
    runs = con.execute("SELECT COUNT(DISTINCT first_run) c FROM jobs").fetchone()["c"]
    print(f"total unique jobs : {total}")
    print(f"across run files  : {runs}")
    print(f"salary known      : {with_pay}/{total} ({with_pay / total:.0%})")
    print("\nby job type:")
    for r in con.execute(
        "SELECT COALESCE(NULLIF(job_type,''),'(unknown)') t, COUNT(*) c FROM jobs "
        "GROUP BY t ORDER BY c DESC LIMIT 8"
    ):
        print(f"  {r['c']:4d}  {r['t']}")
    print("\ntop employers:")
    for r in con.execute(
        "SELECT COALESCE(NULLIF(company,''),'(unknown)') t, COUNT(*) c FROM jobs "
        "GROUP BY t ORDER BY c DESC LIMIT 12"
    ):
        print(f"  {r['c']:4d}  {r['t']}")
    con.close()
    return 0


def _add_shape(p):
    p.add_argument("--match", help="FTS5 query over title/company/description")
    p.add_argument("--company")
    p.add_argument("--location")
    p.add_argument("--job-type", dest="job_type")
    p.add_argument("--min-hourly", dest="min_hourly", type=float)
    p.add_argument("--min-annual", dest="min_annual", type=float)
    p.add_argument("--since", help="date_posted >= YYYY-MM-DD")
    p.add_argument("--run", type=int, help="only rows seen in run >= N")
    p.add_argument("--remote", action="store_true")
    p.add_argument("--onsite", action="store_true")
    p.add_argument("--sort", choices=["date", "salary", "company", "title"], default="date")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--urls", action="store_true", help="print URLs only")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="jobsview", description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--db", default="data/jobs.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ap.add_argument(
        "--queries", default="queries.txt",
        help="family map: queries.txt whose '# --- Family ---' headers name each family",
    )

    p_ingest = sub.add_parser("ingest", help="load data/jobs_*.csv into SQLite")
    p_ingest.set_defaults(func=cmd_ingest)

    p_search = sub.add_parser("search", help="filter jobs")
    _add_shape(p_search)
    p_search.set_defaults(func=cmd_search)

    p_new = sub.add_parser("new", help="jobs seen only in the newest scrape")
    _add_shape(p_new)
    p_new.set_defaults(func=cmd_new)

    p_stats = sub.add_parser("stats", help="coverage + employer concentration")
    p_stats.set_defaults(func=cmd_stats)
    p_review = sub.add_parser("review", help="the review bench: work the queue in a TUI")
    p_review.add_argument(
        "--list", action="store_true",
        help="print the joined queue as text instead of launching the bench",
    )
    p_review.set_defaults(func=cmd_review)

    p_export = sub.add_parser(
        "export",
        help="write <data-dir>/survivors.csv: every kept row, for the resume step",
    )
    p_export.add_argument(
        "--output",
        help="output path (default: <data-dir>/survivors.csv); overwrites every run",
    )
    p_export.set_defaults(func=cmd_export)

    p_kanban = sub.add_parser(
        "kanban",
        help="write the kanban.nvim board (one-way overwrite) from kept rows",
    )
    p_kanban.add_argument(
        "--kanban",
        help="output path (default: ~/notes/.../application-process/kanban.md)",
    )
    p_kanban.set_defaults(func=cmd_kanban)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
