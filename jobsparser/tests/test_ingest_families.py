"""Tests for the job-family map, the legacy backfill and the join (ticket 04).

The family comes from `queries.txt` -- the same file a human edits -- so these
tests pin that a stamped label wins, that the 302 legacy rows get a *marked*
guess, and that `jobsview review` ingests on its own once the CSVs move.
"""
import argparse
import csv
import os
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

# The CSVs the scraper writes today, minus the columns nothing here needs.
LEGACY_COLUMNS = [
    "id", "site", "job_url", "job_url_direct", "title", "company", "location",
    "date_posted", "job_type", "interval", "min_amount", "max_amount",
    "is_remote", "description",
]
# What a CSV written after ticket 01 carries on top of that.
LABELLED_COLUMNS = LEGACY_COLUMNS + ["search_term", "term_label"]

RETAIL_TERM = '("retail" OR cashier OR "sales associate")'
IT_TERM = '("help desk" OR "data entry")'
RETAIL = "Retail, Logistics & Specialized Trades"
IT = "IT, Office & Documentation"

# One term above any header, a header, a comment inside a family, a second
# header -- the same shapes the run_queries.sh tests walk. The headerless term
# is in the fixture so that leaving it out of the map is actually asserted.
QUERIES = f'''# a comment above the first term is not a family header
("entry-level" OR "no experience")


# --- {RETAIL} ---
{RETAIL_TERM}

# --- {IT} ---
# a comment between a header and its term does not reset the family
{IT_TERM}
'''


def _row(job_url, title, **over):
    row = {
        "id": "1", "site": "indeed", "job_url": job_url,
        "job_url_direct": "", "title": title, "company": "Employer",
        "location": "Portland, OR", "date_posted": "2026-10-07",
        "job_type": "", "interval": "", "min_amount": "", "max_amount": "",
        "is_remote": "False", "description": "",
    }
    row.update(over)
    return row


class FamilyMapTest(unittest.TestCase):
    """The pure layer: queries.txt -> families, and a title -> a family guess."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.queries = Path(self._tmp.name) / "queries.txt"
        self.queries.write_text(QUERIES, encoding="utf-8")

    def test_each_term_is_filed_under_the_family_header_above_it(self):
        self.assertEqual(
            jobsview.parse_family_map(self.queries),
            {RETAIL_TERM: RETAIL, IT_TERM: IT},
            "run_queries.sh's nearest-preceding-header rule; a term above any "
            "header is absent from the map rather than filed under nothing",
        )

    def test_family_terms_are_the_phrases_inside_each_terms_or_group(self):
        self.assertEqual(
            jobsview.family_terms(self.queries),
            {
                RETAIL: ["retail", "cashier", "sales associate"],
                IT: ["help desk", "data entry"],
            },
        )

    def test_the_longest_phrase_wins_so_the_specific_family_claims_the_row(self):
        terms = {
            "Narrow family": ["sales associate"],
            "Broad family": ["sales"],
        }
        self.assertEqual("Narrow family", jobsview.guess_family("SALES ASSOCIATE - Hardware", terms))
        self.assertEqual("Broad family", jobsview.guess_family("Seasonal sales", terms))

    def test_an_equal_length_phrase_goes_to_the_family_listed_first(self):
        # queries.txt order is the tie-break, which keeps a guess reproducible.
        terms = {"First family": ["cashier"], "Second family": ["cashier"]}
        self.assertEqual("First family", jobsview.guess_family("Cashier - Grocery", terms))

    def test_a_guessed_family_is_case_insensitive_and_none_when_nothing_matches(self):
        terms = {RETAIL: ["cashier"]}
        self.assertEqual(RETAIL, jobsview.guess_family("  Cashier ", terms))
        self.assertIsNone(jobsview.guess_family("Chief Executive Officer", terms))
        self.assertIsNone(jobsview.guess_family("", terms))


class IngestFamiliesTest(unittest.TestCase):
    """The derived layer: family and source land in jobs.db per row."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.db = self.data / "jobs.db"
        self.queries = self.root / "queries.txt"
        self.queries.write_text(QUERIES, encoding="utf-8")

    def run_jobsview(self, *argv):
        return subprocess.run(
            [sys.executable, str(JOBSVIEW), *argv],
            cwd=str(tempfile.gettempdir()),
            capture_output=True, text=True,
        )

    def ingest_args(self):
        return ["--data-dir", str(self.data), "--db", str(self.db),
                "--queries", str(self.queries), "ingest"]

    def review_store(self):
        return jobsview._review_db(argparse.Namespace(data_dir=self.data))

    def write_csv(self, name, rows, columns=LEGACY_COLUMNS):
        path = self.data / name
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def ingest(self, *argv):
        proc = self.run_jobsview(*self.ingest_args())
        self.assertEqual(0, proc.returncode, proc.stderr)
        return proc

    def job(self, job_url):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT title, job_family, job_family_source FROM jobs WHERE job_url = ?",
            (job_url,),
        ).fetchone()
        con.close()
        return row

    # -- the three sources -------------------------------------------------

    def test_a_stamped_label_wins_over_what_the_map_would_say(self):
        # The label is deliberately a different family from the map's answer.
        self.write_csv("jobs_0.csv", [
            _row("https://indeed.com/job/one", "Data entry clerk",
                 search_term=RETAIL_TERM, term_label=IT),
        ], LABELLED_COLUMNS)

        self.ingest()

        row = self.job("https://indeed.com/job/one")
        self.assertEqual(IT, row["job_family"])
        self.assertEqual("stamped", row["job_family_source"])

    def test_a_legacy_row_gets_a_family_guessed_from_its_title_and_flagged(self):
        self.write_csv("jobs_0.csv", [
            _row("https://indeed.com/job/cashier", "CASHIER - Grocery Store"),
            _row("https://indeed.com/job/helpdesk", "Help Desk Technician"),
        ])

        self.ingest()

        row = self.job("https://indeed.com/job/cashier")
        self.assertEqual(RETAIL, row["job_family"])
        self.assertEqual("inferred", row["job_family_source"])
        self.assertEqual(
            (IT, "inferred"),
            (self.job("https://indeed.com/job/helpdesk")["job_family"],
             self.job("https://indeed.com/job/helpdesk")["job_family_source"]),
        )

    def test_a_row_matching_no_term_and_carrying_no_label_is_unknown(self):
        self.write_csv("jobs_0.csv", [
            _row("https://indeed.com/job/ceo", "Chief Executive Officer"),
        ])

        self.ingest()

        row = self.job("https://indeed.com/job/ceo")
        self.assertEqual("(unknown)", row["job_family"])
        self.assertEqual("unknown", row["job_family_source"])

    def test_a_term_found_in_the_map_without_a_label_is_still_only_inferred(self):
        # The family was recovered from queries.txt, not recorded on the row,
        # so it must carry the display-only flag like every other recovery.
        self.write_csv("jobs_0.csv", [
            _row("https://indeed.com/job/one", "Anything At All",
                 search_term=RETAIL_TERM, term_label=""),
        ], LABELLED_COLUMNS)

        self.ingest()

        row = self.job("https://indeed.com/job/one")
        self.assertEqual(RETAIL, row["job_family"])
        self.assertEqual("inferred", row["job_family_source"])

    def test_new_csv_columns_survive_a_legacy_csv_first_in_the_run(self):
        # The real data/jobs_0.csv is legacy, so a labelled jobs_1.csv arriving
        # later must not lose term_label to a first-header-only table.
        self.write_csv("jobs_0.csv", [_row("https://indeed.com/job/old", "Cashier")])
        self.write_csv("jobs_1.csv", [
            _row("https://indeed.com/job/new", "Data entry clerk",
                 search_term=RETAIL_TERM, term_label=IT),
        ], LABELLED_COLUMNS)

        self.ingest()

        self.assertEqual(
            ("inferred", RETAIL),
            (self.job("https://indeed.com/job/old")["job_family_source"],
             self.job("https://indeed.com/job/old")["job_family"]),
        )
        self.assertEqual(
            ("stamped", IT),
            (self.job("https://indeed.com/job/new")["job_family_source"],
             self.job("https://indeed.com/job/new")["job_family"]),
        )


    def test_a_later_labelled_run_beats_the_guess_backfilled_for_a_row(self):
        # First writer keeps the row, so a legacy row would otherwise carry its
        # guess forever even once a scrape records the family for the same URL.
        self.write_csv("jobs_0.csv", [_row("https://indeed.com/job/one", "Cashier - Grocery")])
        self.write_csv("jobs_1.csv", [
            _row("https://indeed.com/job/one", "Cashier - Grocery",
                 search_term=IT_TERM, term_label=IT),
        ], LABELLED_COLUMNS)

        self.ingest()

        row = self.job("https://indeed.com/job/one")
        self.assertEqual(("stamped", IT), (row["job_family_source"], row["job_family"]))

    def test_the_first_family_to_name_a_row_keeps_it(self):
        # Two stamps must not fight: dedup stays first-writer-wins.
        self.write_csv("jobs_0.csv", [
            _row("https://indeed.com/job/one", "Data entry clerk",
                 search_term=RETAIL_TERM, term_label=RETAIL),
            _row("https://indeed.com/job/one", "Data entry clerk",
                 search_term=IT_TERM, term_label=IT),
        ], LABELLED_COLUMNS)

        self.ingest()

        row = self.job("https://indeed.com/job/one")
        self.assertEqual(("stamped", RETAIL), (row["job_family_source"], row["job_family"]))


class ReviewAutoIngestTest(unittest.TestCase):
    """`jobsview review` ingests on its own, then shows the joined queue."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.db = self.data / "jobs.db"
        self.queries = self.root / "queries.txt"
        self.queries.write_text(QUERIES, encoding="utf-8")

    def run_jobsview(self, *argv):
        return subprocess.run(
            [sys.executable, str(JOBSVIEW), "--data-dir", str(self.data),
             "--db", str(self.db), "--queries", str(self.queries), *argv],
            cwd=str(tempfile.gettempdir()),
            capture_output=True, text=True,
        )

    def write_csv(self, name, rows, columns=LABELLED_COLUMNS):
        path = self.data / name
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def review_args(self):
        return argparse.Namespace(data_dir=self.data, db=self.db, queries=self.queries)

    # -- auto-ingest -------------------------------------------------------

    def test_review_ingests_by_itself_and_only_while_the_csvs_are_newer(self):
        self.write_csv("jobs_0.csv", [_row("https://indeed.com/job/cashier", "Cashier - Grocery")])

        first = self.run_jobsview("review", "--list")
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertIn("ingested", first.stdout)

        second = self.run_jobsview("review", "--list")
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertNotIn("ingested", second.stdout, "nothing moved: do not rebuild the index")

        os.utime(self.data / "jobs_0.csv", None)  # a newer scrape overwrites it
        third = self.run_jobsview("review", "--list")
        self.assertEqual(0, third.returncode, third.stderr)
        self.assertIn("ingested", third.stdout)

    def test_an_index_built_before_the_family_map_is_rebuilt(self):
        # The jobs.db sitting in data/ today predates job_family: no CSV ever
        # moves again, so only the index's shape can reveal it is out of date.
        self.write_csv("jobs_0.csv", [_row("https://indeed.com/job/cashier", "Cashier - Grocery")])
        old = sqlite3.connect(self.db)
        old.execute(
            "CREATE TABLE jobs (rowid INTEGER PRIMARY KEY, job_url TEXT, title TEXT, company TEXT,"
            " location TEXT, date_posted TEXT, job_type TEXT, interval TEXT, min_amount TEXT,"
            " max_amount TEXT, is_remote TEXT, description TEXT, first_run INTEGER, last_run INTEGER,"
            " hourly_min REAL, hourly_max REAL, annual_min REAL, annual_max REAL)"
        )
        old.commit()
        old.close()
        future = self.db.stat().st_mtime + 60  # newer than every CSV
        os.utime(self.db, (future, future))

        proc = self.run_jobsview("review", "--list")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("ingested", proc.stdout, "an index missing job_family is not current")
        self.assertIn(RETAIL, proc.stdout)

    def test_review_with_no_db_and_no_csvs_says_run_ingest(self):
        proc = self.run_jobsview("review", "--list")
        self.assertEqual(1, proc.returncode)
        self.assertIn("run: python3 jobsview.py ingest", proc.stderr)
        self.assertEqual("", proc.stdout)

    # -- the join ----------------------------------------------------------

    def test_the_list_joins_on_job_url_and_flags_what_was_guessed(self):
        rows = [
            _row("https://indeed.com/job/cashier", "Cashier - Grocery"),
            _row("https://indeed.com/job/ceo", "Chief Executive Officer"),
            _row("https://indeed.com/job/helpdesk", "Help Desk Technician",
                 search_term=IT_TERM, term_label=IT),
        ]
        self.write_csv("jobs_0.csv", rows)

        proc = self.run_jobsview("review", "--list")
        self.assertEqual(0, proc.returncode, proc.stderr)
        lines = [ln for ln in proc.stdout.splitlines() if "indeed.com/job/" in ln]
        self.assertEqual(3, len(lines))
        by_url = {ln.split()[-1]: ln for ln in lines}

        cashier = by_url["https://indeed.com/job/cashier"]
        self.assertIn("Cashier", cashier)
        self.assertIn(RETAIL, cashier)
        self.assertIn("(inferred)", cashier)
        self.assertIn("unreviewed", cashier)
        self.assertIn("none", cashier)

        ceo = by_url["https://indeed.com/job/ceo"]
        self.assertIn("(unknown)", ceo)
        self.assertNotIn("(inferred)", ceo)

        helpdesk = by_url["https://indeed.com/job/helpdesk"]
        self.assertIn(IT, helpdesk)
        self.assertNotIn("(inferred)", helpdesk)

    def test_a_decision_survives_the_automatic_ingest_and_shows_on_its_line(self):
        self.write_csv("jobs_0.csv", [_row("https://indeed.com/job/cashier", "Cashier - Grocery")])

        con = jobsview._review_db(self.review_args())
        jobsview.set_decision(con, "https://indeed.com/job/cashier", "keep")
        jobsview.set_application_status(con, "https://indeed.com/job/cashier", "applied")
        con.close()

        proc = self.run_jobsview("review", "--list")
        self.assertEqual(0, proc.returncode, proc.stderr)
        line = [ln for ln in proc.stdout.splitlines() if "cashier" in ln][0]
        self.assertIn("keep", line)
        self.assertIn("applied", line)

    def test_a_csv_missing_a_display_column_reports_it_rather_than_lying(self):
        # The job queue reads title/company/location/date, so a hand-trimmed CSV
        # cannot be listed -- and the message has to name the real cause rather
        # than claiming the index cannot be opened.
        path = self.data / "jobs_0.csv"
        path.write_text("job_url,title\nhttps://indeed.com/job/x,Cashier - Grocery\n",
                        encoding="utf-8")

        proc = self.run_jobsview("review", "--list")
        self.assertEqual(1, proc.returncode)
        self.assertIn("cannot list the queue", proc.stderr)
        self.assertIn("no such column", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_an_index_with_no_csv_beside_it_is_listed_not_rebuilt(self):
        # The CSVs are the scrape's output, so pruning them must not make the
        # queue report the index missing and tell the user to run an ingest
        # that cannot succeed.
        self.write_csv("jobs_0.csv", [_row("https://indeed.com/job/cashier", "Cashier - Grocery")])
        first = self.run_jobsview("review", "--list")
        self.assertEqual(0, first.returncode, first.stderr)
        (self.data / "jobs_0.csv").unlink()

        second = self.run_jobsview("review", "--list")
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertNotIn("run: python3 jobsview.py ingest", second.stderr)
        self.assertIn("cashier", second.stdout)

    def test_an_unreadable_family_map_degrades_the_families_not_the_run(self):
        self.write_csv("jobs_0.csv", [_row("https://indeed.com/job/cashier", "Cashier - Grocery")])
        bad_bytes = self.root / "bad.txt"
        bad_bytes.write_bytes(b"# --- broken ---\xff\xfe\n")

        for label, path in (("a directory", self.data), ("a non-UTF-8 file", bad_bytes)):
            with self.subTest(family_map=label):
                if self.db.exists():
                    self.db.unlink()  # each case needs its own ingest
                proc = self.run_jobsview("--queries", str(path), "review", "--list")
                self.assertEqual(0, proc.returncode, proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertIn("cashier", proc.stdout)
                self.assertIn("(unknown)", proc.stdout, "no map means no guess either")

    def test_a_run_file_with_no_rows_lists_empty_instead_of_failing(self):
        self.write_csv("jobs_0.csv", [])

        proc = self.run_jobsview("review", "--list")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("no jobs", proc.stdout.lower())

    def test_an_inferred_row_is_never_left_out_of_the_queue(self):
        rows = [
            _row(f"https://indeed.com/job/{i}", title)
            for i, title in enumerate(
                ("Cashier - Grocery", "Chief Executive Officer", "Help Desk Tech")
            )
        ]
        self.write_csv("jobs_0.csv", rows)

        proc = self.run_jobsview("review", "--list")
        self.assertEqual(0, proc.returncode, proc.stderr)
        listed = [ln for ln in proc.stdout.splitlines() if "indeed.com/job/" in ln]
        self.assertEqual(len(rows), len(listed))
        self.assertIn(
            "(inferred)", proc.stdout,
            "a guess is display-only, never a reason to drop a row",
        )


if __name__ == "__main__":
    unittest.main()
