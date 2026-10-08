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


def cmd_ingest(args) -> int:
    data_dir = Path(args.data_dir)
    files = _run_files(data_dir)
    if not files:
        print(f"no jobs_*.csv under {data_dir}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    seen: dict[str, int] = {}
    header: list[str] = []
    for run_no, path in ((RUN_RE.search(p.name).group(1), p) for p in files):
        run_no = int(run_no)
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not header:
                header = list(reader.fieldnames or [])
            for row in reader:
                url = (row.get("job_url") or "").strip()
                if not url:
                    continue
                if url in seen:
                    rows[seen[url]]["last_run"] = run_no
                    continue
                hmin, hmax, amin, amax = derive_pay(row)
                row["first_run"] = run_no
                row["last_run"] = run_no
                row["hourly_min"], row["hourly_max"] = hmin, hmax
                row["annual_min"], row["annual_max"] = amin, amax
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
    print(f"salary known for {with_salary}/{n} ({with_salary / n:.0%})")
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


def cmd_review(args) -> int:
    if getattr(args, "list", False):
        return cmd_review_list(args)
    print("nothing to do -- try: python3 jobsview.py review --list", file=sys.stderr)
    return 2


def cmd_review_list(args) -> int:
    """Print the store one row per line, so state can be seen without the TUI."""
    try:
        con = _review_db(args)
    except (OSError, sqlite3.Error) as err:
        db = Path(args.data_dir) / "review.db"
        print(f"cannot open {db}: {err}", file=sys.stderr)
        return 1
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT job_url, decision, application_status, first_run, last_run, "
        "decided_at, updated_at FROM jobs_review ORDER BY job_url"
    ).fetchall()
    con.close()
    if not rows:
        print("(review store is empty)")
        return 0
    for r in rows:
        cells = [r["job_url"], r["decision"], r["application_status"]]
        cells += ["-" if r[c] is None else str(r[c])
                  for c in ("first_run", "last_run", "decided_at", "updated_at")]
        print("  ".join(cells))
    return 0


def _open(args):
    db = Path(args.db)
    if not db.exists():
        print(f"{db} missing -- run: python3 jobsview.py ingest", file=sys.stderr)
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


def _build_query(args):
    where, params = [], []
    fts = False
    if getattr(args, "match", None):
        fts = True
        where.append("j.rowid IN (SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?)")
        params.append(args.match)
    if getattr(args, "company", None):
        where.append("j.company LIKE ?")
        params.append(f"%{args.company}%")
    if getattr(args, "location", None):
        where.append("j.location LIKE ?")
        params.append(f"%{args.location}%")
    if getattr(args, "job_type", None):
        where.append("j.job_type LIKE ?")
        params.append(f"%{args.job_type}%")
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
    p_review = sub.add_parser("review", help="inspect the review store (data/review.db)")
    p_review.add_argument("--list", action="store_true", help="print every row, one per line")
    p_review.set_defaults(func=cmd_review)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
