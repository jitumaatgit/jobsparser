"""Ticket 01 -- every scraped row carries its provenance.

Seam: the CLI. Each test runs the command through Click's ``CliRunner`` with
``scrape_jobs`` replaced at the network boundary, then reads the written CSV
back. The CSV is what the rest of the pipeline (``jobsview ingest``, the review
bench) consumes, so assertions live on its parsed contents and not on the
internals that produced them.
"""
from __future__ import annotations

import csv
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


import pandas as pd
from click.testing import CliRunner

# A stub `jobsparser/__init__.py` sits at this repo's project-directory root, so any run
# whose sys.path[0] is the repo root resolves `import jobsparser` to that empty package and
# `jobsparser.cli` disappears underneath it. Force the real source tree to the front so
# these tests exercise the installed package whatever directory they run from. Position
# matters, not mere presence: the editable install already puts this directory on
# sys.path, but behind the current directory, where the stub still wins.
_SRC = str(Path(__file__).resolve().parents[2] / "jobsparser" / "src")
if _SRC in sys.path:
    sys.path.remove(_SRC)
sys.path.insert(0, _SRC)

import jobsparser.cli as cli
from jobsparser.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]

# One page of three rows. Small enough that a run is fast, big enough that the
# CSV has several rows to assert over.
_ONE_PAGE = [
    "--location", "Portland, OR",
    "--results-wanted", "3",
    "--batch-size", "3",
    "--sleep-time", "0",
    "--max-retries", "1",
]


class _FakeScrapeJobs:
    """Stands in for ``jobspy.scrape_jobs`` at the network boundary.

    Returns one page of ``results_wanted`` records per call. ``keyed_by`` picks
    how ``job_url`` is built, because ``job_url`` is the CLI's dedup key:

    ``term``    every call advertises fresh URLs, so each term adds rows.
    ``shared``  every call returns the same URLs, so later terms dedupe.
    """

    def __init__(self, keyed_by: str = "term"):
        self.keyed_by = keyed_by
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        wanted = kwargs["results_wanted"]
        offset = kwargs.get("offset") or 0
        salt = self.calls if self.keyed_by == "term" else "shared"
        return pd.DataFrame(
            [
                {
                    "site": kwargs["site_name"],
                    "job_url": f"https://example.invalid/job/{salt}/{offset + i}",
                    "job_url_direct": f"https://example.invalid/apply/{salt}/{offset + i}",
                    "title": f"Stub job {offset + i}",
                    "company": "Acme",
                    "location": "Portland, OR, US",
                    "date_posted": "2026-10-08",
                    "job_type": "fulltime",
                    "interval": "hourly",
                    "min_amount": 18.0,
                    "max_amount": 22.0,
                    "description": "Stub description.",
                }
                for i in range(wanted)
            ]
        )


class Ticket01Provenance(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()
        self.scrape_jobs = _FakeScrapeJobs()
        patcher = mock.patch.object(cli, "scrape_jobs", self.scrape_jobs)
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name) / "out"

    def _run(self, *extra):
        return self.runner.invoke(
            main,
            [*_ONE_PAGE, *extra, "--output-dir", str(self.out)],
        )

    def _csv(self):
        with (self.out / "jobs_0.csv").open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            return list(reader.fieldnames or []), list(reader)

    def test_row_carries_the_raw_search_term_and_its_family_label(self):
        result = self._run(
            "--search-term", '"data entry"',
            "--term-label", "IT, Office & Documentation",
        )
        self.assertEqual(result.exit_code, 0, result.output)

        header, rows = self._csv()
        self.assertTrue(rows)
        self.assertLessEqual({"search_term", "term_label"}, set(header))
        # The label contains a comma: it must survive CSV quoting verbatim.
        self.assertEqual(
            {(r["search_term"], r["term_label"]) for r in rows},
            {('"data entry"', "IT, Office & Documentation")},
        )

    def test_omitting_term_label_writes_the_empty_string(self):
        result = self._run("--search-term", '"data entry"')
        self.assertEqual(result.exit_code, 0, result.output)

        header, rows = self._csv()
        self.assertIn("term_label", header)
        self.assertEqual(
            {r["term_label"] for r in rows},
            {""},
            "an absent label must be the empty string, never None or a placeholder",
        )
        self.assertEqual({r["search_term"] for r in rows}, {'"data entry"'})

    def test_label_count_mismatch_is_a_usage_error_before_any_work(self):
        result = self._run(
            "--search-term", "retail",
            "--search-term", "warehouse",
            "--term-label", "Only one label",
        )
        self.assertEqual(result.exit_code, 2)
        self.assertIn("--term-label", result.output)
        self.assertIn("--search-term", result.output)
        self.assertFalse(
            self.out.exists(),
            "a bad invocation must not create the output directory or scrape",
        )
        self.assertEqual(self.scrape_jobs.calls, 0)

    def test_labels_pair_with_search_terms_by_position(self):
        result = self._run(
            "--search-term", "retail",
            "--term-label", "Retail, Logistics & Specialized Trades",
            "--search-term", "help desk",
            "--term-label", "IT, Office & Documentation",
        )
        self.assertEqual(result.exit_code, 0, result.output)

        _, rows = self._csv()
        self.assertEqual(
            {r["search_term"]: r["term_label"] for r in rows},
            {
                "retail": "Retail, Logistics & Specialized Trades",
                "help desk": "IT, Office & Documentation",
            },
        )

    def test_one_job_url_reported_by_two_terms_is_stored_once(self):
        """Dedup stays keyed on job_url across terms: first writer keeps the row."""
        self.scrape_jobs.keyed_by = "shared"
        result = self._run(
            "--search-term", "retail",
            "--term-label", "Retail, Logistics & Specialized Trades",
            "--search-term", "warehouse",
            "--term-label", "Entry-level, catch-all",
        )
        self.assertEqual(result.exit_code, 0, result.output)

        _, rows = self._csv()
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["search_term"] for r in rows}, {"retail"})
        self.assertEqual({r["term_label"] for r in rows}, {"Retail, Logistics & Specialized Trades"})
        self.assertEqual(len({r["job_url"] for r in rows}), 3)

    def test_jobsview_ingest_still_loads_a_labelled_csv(self):
        """The ingest derives its table from the CSV header, so new columns are a
        real risk to it -- this pins that they still land."""
        result = self._run(
            "--search-term", '"data entry"',
            "--term-label", "IT, Office & Documentation",
        )
        self.assertEqual(result.exit_code, 0, result.output)

        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "jobsview.py"),
             "--data-dir", str(self.out), "--db", str(self.out / "jobs.db"), "ingest"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        con = sqlite3.connect(self.out / "jobs.db")
        try:
            columns = {row[1] for row in con.execute("PRAGMA table_info(jobs)")}
            rows = con.execute("SELECT search_term, term_label FROM jobs").fetchall()
        finally:
            con.close()
        self.assertLessEqual({"search_term", "term_label"}, columns)
        self.assertTrue(rows)
        self.assertEqual(rows[0], ('"data entry"', "IT, Office & Documentation"))


if __name__ == "__main__":
    unittest.main()
