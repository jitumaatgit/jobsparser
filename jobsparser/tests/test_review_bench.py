"""Headless acceptance tests for the review bench (ticket 05)."""
import argparse
import contextlib
import csv
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import jobsview  # noqa: E402

# Textual is optional -- `make bench-setup` installs it -- so the suite must
# still be discoverable, and must still check the stdlib-only guarantee, on a
# plain `make setup`.
try:
    from jobsview_tui import ReviewBenchApp
    from textual.widgets import DataTable, RichLog, Static
except ModuleNotFoundError:  # pragma: no cover - the skip below covers this
    ReviewBenchApp = DataTable = RichLog = Static = None

BENCH = unittest.skipUnless(
    ReviewBenchApp, "run: make bench-setup to install Textual for the review bench tests"
)

JOBSVIEW = REPO_ROOT / "jobsview.py"
CSV_COLUMNS = (
    "job_url", "job_url_direct", "title", "company", "location",
    "date_posted", "description", "search_term", "term_label",
    "min_amount", "max_amount",
)


def _row(number, title, **overrides):
    row = {
        "job_url": f"https://indeed.com/job/{number}",
        "job_url_direct": f"https://employer.example/jobs/{number}",
        "title": title,
        "company": "Example Employer",
        "location": "Portland, OR",
        "date_posted": "2026-10-07",
        "description": "## Responsibilities\n\n- Help customers\n- Keep records",
        "search_term": '"cashier"',
        "term_label": "Retail",
        "min_amount": "18",
        "max_amount": "23",
    }
    row.update(overrides)
    return row


@BENCH
class ReviewBenchTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.db = self.data / "jobs.db"
        self.queries = self.data / "queries.txt"
        self.queries.write_text('# --- Retail ---\n"cashier"\n', encoding="utf-8")
        self.args = argparse.Namespace(
            data_dir=str(self.data), db=str(self.db), queries=str(self.queries),
        )

    def build_index(self, rows):
        with (self.data / "jobs_0.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, jobsview.cmd_ingest(self.args))

    def selected_title(self, app):
        table = app.query_one("#queue", DataTable)
        cell = table.get_row_at(table.cursor_row)[0]
        return cell.plain if hasattr(cell, "plain") else str(cell)

    def listing(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, jobsview.cmd_review_list(self.args))
        return output.getvalue()

    async def test_space_advances_and_undo_restores_both_axes_and_cursor(self):
        self.build_index([
            _row("one", "Cashier One"),
            _row("two", "Cashier Two"),
            _row("three", "Cashier Three"),
        ])
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#queue", DataTable)
            self.assertEqual(3, table.row_count)
            self.assertEqual("Cashier One", self.selected_title(app))

            await pilot.press("a")
            await pilot.pause()
            self.assertEqual("Cashier Two", self.selected_title(app))

            await pilot.press("k")
            self.assertEqual("Cashier One", self.selected_title(app))
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual("Cashier Two", self.selected_title(app))
            self.assertEqual(2, table.row_count)

            # The decision action preserved the application status set earlier.
            state = self.listing()
            first_line = next(line for line in state.splitlines() if "job/one" in line)
            self.assertIn("keep", first_line)
            self.assertIn("applied", first_line)

            await pilot.press("ctrl+z")
            await pilot.pause()
            self.assertEqual(3, table.row_count)
            self.assertEqual("Cashier One", self.selected_title(app))
            undone_decision = self.listing()
            first_line = next(line for line in undone_decision.splitlines() if "job/one" in line)
            self.assertIn("unreviewed", first_line)
            self.assertIn("applied", first_line)

            await pilot.press("ctrl+z")
            await pilot.pause()
            undone_status = self.listing()
            first_line = next(line for line in undone_status.splitlines() if "job/one" in line)
            self.assertIn("unreviewed", first_line)
            self.assertIn("none", first_line)
            self.assertIn("Undid", str(app.query_one("#undo-status", Static).render()))

    async def test_a_key_that_changes_nothing_still_advances(self):
        # "Auto-advance after any action": pressing `0` on a row already at
        # `none` is still an action, and the store must not gain a row for it.
        self.build_index([_row("one", "Cashier One"), _row("two", "Cashier Two")])
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual("Cashier One", self.selected_title(app))

            await pilot.press("0")
            await pilot.pause()

            self.assertEqual("Cashier Two", self.selected_title(app))
            self.assertEqual(2, app.query_one("#queue", DataTable).row_count)
            self.assertEqual([], app._undo_stack, "nothing changed, so nothing to undo")
        first_line = next(ln for ln in self.listing().splitlines() if "job/one" in ln)
        self.assertIn("unreviewed", first_line)
        self.assertIn("none", first_line)

    async def test_detail_browser_and_direct_review_keys(self):
        self.build_index([
            _row("one", "Cashier One"),
            _row("two", "Cashier Two", job_url_direct=""),
        ])
        app = ReviewBenchApp(self.args)

        with patch("jobsview_tui.webbrowser.open") as open_url:
            async with app.run_test() as pilot:
                await pilot.pause()
                detail = app.query_one("#description", RichLog)
                await pilot.press("enter")
                await pilot.pause()
                self.assertIs(app.focused, detail)
                rendered = "".join(
                    segment.text for line in detail.lines for segment in line
                )
                self.assertIn("Responsibilities", rendered)
                self.assertIn("Help customers", rendered)  # body, not the raw '- ' marker
                self.assertIn("https://employer.example/jobs/one", rendered)
                await pilot.press("v")
                open_url.assert_called_once_with("https://employer.example/jobs/one")

                await pilot.press("j")
                await pilot.press("v")
                open_url.assert_called_with("https://indeed.com/job/two")
                await pilot.press("f")
                await pilot.pause()

        state = self.listing()
        second_line = next(line for line in state.splitlines() if "job/two" in line)
        self.assertIn("false_positive", second_line)

    def _two_thousand(self):
        self.build_index([_row(str(n), f"Cashier {n:04}") for n in range(2000)])
        return ReviewBenchApp(self.args)

    def column_widths(self, app):
        table = app.query_one("#queue", DataTable)
        return {key: table.columns[key].get_render_width(table)
                for key in table.columns.keys()}

    async def test_the_queue_draws_every_column_at_an_ordinary_terminal_width(self):
        # The widths this shipped with summed to more cells than an ordinary
        # terminal hands the queue, so Textual drew only four of the eight --
        # Pay, Job family, Decision and Status were absent from the screen, the
        # two axes that are the whole point, with no key that reached them.
        # Widths must therefore be derived from the space actually there.
        self.build_index([_row("one", "Cashier One"), _row("two", "Cashier Two")])
        app = ReviewBenchApp(self.args)

        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            table = app.query_one("#queue", DataTable)
            widths = self.column_widths(app)

            self.assertEqual(
                ["title", "company", "location", "date", "pay", "family", "decision", "status"],
                list(table.columns.keys()),
            )
            self.assertGreaterEqual(widths["family"], len("Job family"))
            self.assertLessEqual(
                sum(widths.values()), table.size.width,
                "a column past the queue's width is not drawn, it is simply lost",
            )
            # Decision displays `unreviewed`; status displays `interview`.
            self.assertGreaterEqual(widths["decision"], len("unreviewed"))
            self.assertGreaterEqual(widths["status"], len("interview"))

    async def test_the_columns_reflow_when_the_terminal_is_resized(self):
        self.build_index([_row("one", "Cashier One"), _row("two", "Cashier Two")])
        app = ReviewBenchApp(self.args)

        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            table = app.query_one("#queue", DataTable)
            narrow = self.column_widths(app)

            await pilot.resize_terminal(62, 28)
            await pilot.pause()
            small = self.column_widths(app)
            self.assertGreater(sum(small.values()), table.size.width)

            await pilot.resize_terminal(140, 40)
            await pilot.pause()
            restored = self.column_widths(app)
            self.assertEqual(table.size.width, sum(restored.values()))

            await pilot.resize_terminal(240, 40)
            await pilot.pause()
            wide = self.column_widths(app)

            self.assertEqual(table.size.width, sum(wide.values()))
            self.assertGreater(wide["title"], narrow["title"])
            # Extra room must never cost a column.
            self.assertEqual(len(narrow), len(wide))

    async def test_a_narrow_terminal_keeps_columns_reachable_by_arrow_keys(self):
        self.build_index([_row("one", "Cashier One"), _row("two", "Cashier Two")])
        app = ReviewBenchApp(self.args)

        async with app.run_test(size=(62, 28)) as pilot:
            await pilot.pause()
            table = app.query_one("#queue", DataTable)
            self.assertGreater(
                sum(self.column_widths(app).values()), table.size.width,
                "narrow view keeps legible column widths and scrolls instead of crushing them",
            )
            self.assertEqual(0, table.scroll_x)

            await pilot.press("right")
            await pilot.pause()
            self.assertGreater(table.scroll_x, 0)

            await pilot.press("left")
            await pilot.pause()
            self.assertEqual(0, table.scroll_x)

    async def test_the_footer_keeps_the_safety_net_on_an_ordinary_terminal(self):
        # The original sixteen shown bindings ran past a 140-column footer,
        # hiding Undo and Quit even though undo is the safety net for a mis-keyed
        # `f`.
        self.build_index([_row("one", "Cashier One"), _row("two", "Cashier Two")])
        app = ReviewBenchApp(self.args)

        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            screen = app.export_screenshot()

        self.assertIn("Undo", screen)
        self.assertIn("Quit", screen)

    async def test_two_thousand_rows_navigate_the_virtual_table(self):
        app = self._two_thousand()

        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#queue", DataTable)
            self.assertEqual(2000, table.row_count)
            self.assertEqual("Cashier 0000", self.selected_title(app))
            for _ in range(5):
                await pilot.press("j")
            await pilot.pause()
            self.assertEqual("Cashier 0005", self.selected_title(app))
            await pilot.press("k")
            await pilot.pause()
            self.assertEqual("Cashier 0004", self.selected_title(app))

    async def test_acting_on_one_row_never_rebuilds_the_two_thousand_row_table(self):
        # "Thousands of rows must stay smooth" is a claim about cost: acting on
        # one row must touch one row. Rebuilding the table per keystroke is the
        # way to get that wrong, and it is invisible to a behaviour-only test,
        # so this watches the one call a rebuild cannot avoid making.
        app = self._two_thousand()

        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#queue", DataTable)
            self.assertEqual(2000, table.row_count)

            added: list[tuple] = []
            add_row = table.add_row
            table.add_row = lambda *cells, **kwargs: (
                added.append(cells), add_row(*cells, **kwargs)
            )[1]

            await pilot.press("f")
            await pilot.pause()

            self.assertEqual([], added, "one decision must not rebuild the table")
            self.assertEqual(1999, table.row_count)
            self.assertEqual("Cashier 0001", self.selected_title(app))

    async def test_review_without_list_launches_the_bench_and_ingests_first(self):
        # No --list means the TUI, so the CLI must reach the launch point rather
        # than the old "nothing to do" message, having built the index first.
        self.build_index([_row("one", "Cashier One")])
        (self.data / "jobs.db").unlink()
        launched = []

        with patch.object(ReviewBenchApp, "run", lambda self: launched.append(self.args)):
            self.assertEqual(0, jobsview.cmd_review(self.args))

        self.assertTrue(self.db.is_file(), "review must ingest before launching")
        self.assertEqual(1, len(launched))

    async def test_review_list_stays_headless_and_never_launches_the_bench(self):
        self.build_index([_row("one", "Cashier One")])
        self.args.list = True
        with patch.object(ReviewBenchApp, "run", side_effect=AssertionError("must not launch")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(0, jobsview.cmd_review(self.args))
        self.assertIn("job/one", out.getvalue())

class StdlibOnlyTest(unittest.TestCase):
    """The part of the bench contract that must hold with Textual ABSENT.

    This is deliberately outside the `@BENCH` class: it is the test that runs
    on a plain `make setup`, and skipping it where Textual is missing would
    skip exactly the environment it exists to check.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.db = self.data / "jobs.db"
        self.queries = self.data / "queries.txt"
        self.queries.write_text('# --- Retail ---\n"cashier"\n', encoding="utf-8")
        with (self.data / "jobs_0.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerow(_row("one", "Cashier One"))
        args = argparse.Namespace(
            data_dir=str(self.data), db=str(self.db), queries=str(self.queries),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, jobsview.cmd_ingest(args))

    def test_stdlib_subcommands_run_and_review_explains_setup_without_textual(self):
        command = [
            sys.executable, "-S", str(JOBSVIEW),
            "--data-dir", str(self.data), "--db", str(self.db),
            "--queries", str(self.queries),
        ]

        search = subprocess.run(
            [*command, "search", "--limit", "1"], cwd=self.data,
            capture_output=True, text=True,
        )
        self.assertEqual(0, search.returncode, search.stderr)
        self.assertIn("Cashier One", search.stdout)

        review = subprocess.run(
            [*command, "review"], cwd=self.data, capture_output=True, text=True,
        )
        self.assertNotEqual(0, review.returncode)
        self.assertIn("make bench-setup", review.stderr)
        self.assertNotIn("Traceback", review.stderr)


if __name__ == "__main__":
    unittest.main()
