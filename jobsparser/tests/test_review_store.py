"""Tests for the review.db sidecar store (review bench ticket 03).

`review.db` holds the user-authored state -- the review decision, the
application status and the run numbers a row was seen in. It is the only source
of truth for that state, so these tests assert it is created with the exact
schema, survives a separate process, never lets an ingest destroy a decision,
and refuses values from the other axis.
"""
import argparse
import csv
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# jobsview.py is a repo-root script, not an installed package; make it
# importable whatever directory the suite is discovered from.
sys.path.insert(0, str(REPO_ROOT))

import jobsview  # noqa: E402

JOBSVIEW = REPO_ROOT / "jobsview.py"

# The schema from ticket 03, in order.
COLUMNS = (
    ("job_url", "TEXT"),
    ("decision", "TEXT"),
    ("application_status", "TEXT"),
    ("first_run", "INTEGER"),
    ("last_run", "INTEGER"),
    ("decided_at", "TEXT"),
    ("updated_at", "TEXT"),
)

CSV_COLUMNS = ["job_url", "title", "company", "location", "date_posted", "description"]

def _row(job_url, title, **over):
    row = {
        "job_url": job_url, "title": title, "company": "Employer",
        "location": "Portland, OR", "date_posted": "2026-10-07",
        "description": "",
    }
    row.update(over)
    return row

class ReviewStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        self.db_path = self.data_dir / "review.db"
        self.con = jobsview._review_db(argparse.Namespace(data_dir=self.data_dir))
        self.addCleanup(self.con.close)

    def read_row(self, con, job_url):
        con.row_factory = sqlite3.Row
        return con.execute(
            "SELECT * FROM jobs_review WHERE job_url = ?", (job_url,)
        ).fetchone()

    def run_cli(self, *argv, data_dir=None):
        # --db is explicit because the default resolves against the child's
        # cwd (/tmp), which would share one index across every run.
        self.assertTrue(JOBSVIEW.is_file(), f"{JOBSVIEW} is missing")
        target = data_dir or self.data_dir
        return subprocess.run(
            [sys.executable, str(JOBSVIEW), "--data-dir", str(target),
             "--db", str(target / "jobs.db"), *argv],
            cwd=str(tempfile.gettempdir()),
            capture_output=True,
            text=True,
        )

    def write_csv(self, *rows, data_dir=None):
        """One run file of scraped jobs, so the listing has something to join."""
        self.write_csv_to(data_dir or self.data_dir, *rows)

    def write_csv_to(self, data_dir, *rows):
        with (data_dir / "jobs_0.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    # -- schema and lifecycle ----------------------------------------------

    def test_opening_a_missing_review_db_creates_the_exact_schema(self):
        self.assertTrue(self.db_path.is_file(), "opening must create the file")

        info = self.con.execute("PRAGMA table_info(jobs_review)").fetchall()
        self.assertEqual(COLUMNS, tuple((r[1], r[2]) for r in info))
        defaults = {r[1]: (r[4] or "").strip("'") for r in info}
        self.assertEqual("unreviewed", defaults["decision"])
        self.assertEqual("none", defaults["application_status"])
        self.assertEqual(0, self.con.execute("SELECT COUNT(*) FROM jobs_review").fetchone()[0])

    def test_a_read_leaves_the_stored_state_alone(self):
        # `review --list` joins the store into the job listing, so a read must
        # still leave every stored row exactly as it was.
        self.write_csv(_row("https://indeed.com/job/one", "Cashier - Grocery"))
        jobsview.set_decision(self.con, "https://indeed.com/job/one", "keep")
        before = dict(self.read_row(self.con, "https://indeed.com/job/one"))

        proc = self.run_cli("review", "--list")
        self.assertEqual(0, proc.returncode, proc.stderr)

        self.assertTrue(self.db_path.is_file(), "a read must never remove the store")
        after = dict(self.read_row(self.con, "https://indeed.com/job/one"))
        self.assertEqual(before, after)

    def test_a_decision_survives_reopening_in_another_process(self):
        # The store is the only source of truth, so durability is asserted by
        # reading it back from a second interpreter rather than through the
        # job listing (which ticket 04's tests own).
        jobsview.set_decision(self.con, "https://indeed.com/job/keep-me", "keep")
        code = (
            "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);"
            "print(c.execute('SELECT decision,application_status FROM jobs_review "
            "WHERE job_url=?',(sys.argv[2],)).fetchone())"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code, str(self.db_path), "https://indeed.com/job/keep-me"],
            capture_output=True, text=True,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual("('keep', 'none')", proc.stdout.strip())

    # -- the two axes ------------------------------------------------------

    def test_the_two_axes_never_swap_vocabularies(self):
        cases = (
            # field, helper, the other axis' rejection, the other axis' verdict
            ("decision", jobsview.set_decision, "rejected", "applied", "keep"),
            ("application_status", jobsview.set_application_status, "false_positive", "keep", "applied"),
        )
        for field, fn, other_rejection, other_verdict, valid in cases:
            with self.subTest(field=field):
                # The other axis' rejection is not a value on this axis ...
                with self.assertRaises(ValueError) as ctx:
                    fn(self.con, "https://indeed.com/job/axis", other_rejection)
                self.assertIn(other_rejection, str(ctx.exception))
                # ... and neither is its verdict.
                for value in (other_rejection, other_verdict):
                    with self.assertRaises(ValueError):
                        fn(self.con, "https://indeed.com/job/axis", value)
                fn(self.con, "https://indeed.com/job/axis", valid)
                self.assertEqual(valid, self.read_row(self.con, "https://indeed.com/job/axis")[field])
        # Both axes live on one row without either clobbering the other.
        row = self.read_row(self.con, "https://indeed.com/job/axis")
        self.assertEqual("keep", row["decision"])
        self.assertEqual("applied", row["application_status"])

    def test_the_store_itself_refuses_a_value_from_the_other_axis(self):
        # The DDL is effectively write-once, so the storage layer is the one
        # place the two vocabularies can be held apart permanently.
        for column, foreign in (("decision", "rejected"), ("application_status", "false_positive")):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.con.execute(
                        f"INSERT INTO jobs_review (job_url, {column}) VALUES (?, ?)",
                        ("https://indeed.com/job/direct", foreign),
                    )

    # -- defaults, run numbers, timestamps ---------------------------------

    def test_defaults_for_a_newly_inserted_url(self):
        jobsview.ensure_review_row(self.con, "https://indeed.com/job/fresh")
        row = self.read_row(self.con, "https://indeed.com/job/fresh")
        self.assertEqual("unreviewed", row["decision"])
        self.assertEqual("none", row["application_status"])
        self.assertIsNotNone(row["updated_at"])

    def test_seeing_a_row_again_never_destroys_its_state(self):
        # The invariant ticket 04's ingest depends on: the ON CONFLICT branch
        # widens the run range and leaves the decision exactly as it was.
        url = "https://indeed.com/job/seen-again"
        jobsview.ensure_review_row(self.con, url, first_run=5, last_run=5)
        jobsview.set_decision(self.con, url, "keep")
        jobsview.set_application_status(self.con, url, "interview")
        decided = self.read_row(self.con, url)["decided_at"]
        self.assertIsNotNone(decided)

        jobsview.ensure_review_row(self.con, url, first_run=3, last_run=8)

        row = self.read_row(self.con, url)
        self.assertEqual(3, row["first_run"])  # only ever widens
        self.assertEqual(8, row["last_run"])
        self.assertEqual("keep", row["decision"])
        self.assertEqual("interview", row["application_status"])
        self.assertEqual(decided, row["decided_at"])

    def test_seeing_a_row_with_no_new_runs_changes_nothing(self):
        url = "https://indeed.com/job/steady"
        jobsview.ensure_review_row(self.con, url, first_run=4, last_run=4)
        before = dict(self.read_row(self.con, url))

        jobsview.ensure_review_row(self.con, url, first_run=4, last_run=4)

        self.assertEqual(before, dict(self.read_row(self.con, url)))
        self.assertEqual(dict(first_run=4, last_run=4), dict(
            first_run=before["first_run"], last_run=before["last_run"]
        ))

    def test_decided_at_follows_the_decision_the_row_carries(self):
        url = "https://indeed.com/job/undo"
        jobsview.set_decision(self.con, url, "keep")
        first = self.read_row(self.con, url)["decided_at"]
        self.assertIsNotNone(first)

        jobsview.set_decision(self.con, url, "false_positive")
        self.assertEqual(first, self.read_row(self.con, url)["decided_at"])

        # Undoing back to unreviewed is the absence of a decision, so the
        # timestamp must not linger for a later keep to inherit.
        jobsview.set_decision(self.con, url, "unreviewed")
        self.assertIsNone(self.read_row(self.con, url)["decided_at"])
        jobsview.set_decision(self.con, url, "keep")
        self.assertIsNotNone(self.read_row(self.con, url)["decided_at"])

    # -- CLI ---------------------------------------------------------------

    def test_review_list_prints_one_line_per_job_with_both_axes(self):
        # The listing joins jobs to the store, so what the store contributes is
        # the two axes, one per line, in each job's own row.
        self.write_csv(
            _row("https://indeed.com/job/one", "Cashier - Grocery"),
            _row("https://indeed.com/job/two", "Help Desk Technician"),
        )
        jobsview.set_decision(self.con, "https://indeed.com/job/one", "keep")
        jobsview.set_application_status(self.con, "https://indeed.com/job/two", "applied")

        proc = self.run_cli("review", "--list")
        self.assertEqual(0, proc.returncode, proc.stderr)
        lines = [ln for ln in proc.stdout.splitlines() if "indeed.com/job/" in ln]
        self.assertEqual(2, len(lines))
        self.assertIn("https://indeed.com/job/one", lines[0])
        self.assertIn("keep", lines[0])
        self.assertIn("https://indeed.com/job/two", lines[1])
        self.assertIn("applied", lines[1])
        self.assertIn("unreviewed", lines[1])  # that job has no store row yet

    def test_review_list_reports_one_line_when_the_store_cannot_be_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            self.write_csv_to(data, _row("https://indeed.com/job/one", "Cashier - Grocery"))
            first = self.run_cli("review", "--list", data_dir=data)
            self.assertEqual(0, first.returncode, first.stderr)

            (data / "review.db").unlink()
            (data / "review.db").mkdir()  # sqlite cannot open a directory
            second = self.run_cli("review", "--list", data_dir=data)
            self.assertEqual(1, second.returncode)
            self.assertIn("cannot open", second.stderr)
            self.assertNotIn("Traceback", second.stderr)

    def test_review_without_list_does_nothing(self):
        self.write_csv(_row("https://indeed.com/job/one", "Cashier - Grocery"))
        proc = self.run_cli("review")
        self.assertEqual(2, proc.returncode)
        self.assertIn("review --list", proc.stderr)


if __name__ == "__main__":
    unittest.main()
