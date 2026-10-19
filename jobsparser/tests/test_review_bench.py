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
    from textual.widgets import DataTable, Input, RichLog, Static
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


async def type_in_bar(pilot, term: str) -> None:
    """Type a search term into the filter bar the way a keyboard does."""
    for character in term:
        await pilot.press("space" if character == " " else character)


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

    def app_with_two_rows(self):
        self.build_index([_row("one", "Cashier One"), _row("two", "Cashier Two")])
        return ReviewBenchApp(self.args)

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
                await pilot.press("x")
                await pilot.pause()

        state = self.listing()
        second_line = next(line for line in state.splitlines() if "job/two" in line)
        self.assertIn("false_positive", second_line)

    async def test_enter_toggles_focus_between_job_list_and_detail(self):
        app = self.app_with_two_rows()

        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#queue", DataTable)
            detail = app.query_one("#description", RichLog)
            self.assertIs(app.focused, table)
            list_screen = app.export_screenshot()

            await pilot.press("enter")
            await pilot.pause()
            self.assertIs(app.focused, detail)
            detail_screen = app.export_screenshot()
            self.assertNotEqual(
                list_screen, detail_screen,
                "Enter must make the detail-focus change visible",
            )

            await pilot.press("enter")
            await pilot.pause()
            self.assertIs(app.focused, table)

    async def test_ctrl_jk_scrolls_detail_without_leaving_the_job_list(self):
        description = "\n\n".join(
            f"## Section {index}\n\n- Long detail section {index}."
            for index in range(40)
        )
        self.build_index([_row("one", "Cashier One", description=description)])
        app = ReviewBenchApp(self.args)

        async with app.run_test(size=(120, 18)) as pilot:
            await pilot.pause()
            table = app.query_one("#queue", DataTable)
            detail = app.query_one("#description", RichLog)
            self.assertIs(app.focused, table)
            self.assertGreater(detail.scroll_y, 0, "long detail starts with content below view")
            initial_scroll = detail.scroll_y
            initial_row = table.cursor_row

            await pilot.press("ctrl+k")
            await pilot.pause()
            self.assertIs(app.focused, table, "scrolling details must retain list focus")
            self.assertLess(detail.scroll_y, initial_scroll)
            self.assertEqual(initial_row, table.cursor_row)

            scroll_up = detail.scroll_y
            await pilot.press("ctrl+j")
            await pilot.pause()
            self.assertIs(app.focused, table)
            self.assertGreater(detail.scroll_y, scroll_up)
            self.assertEqual(initial_row, table.cursor_row)

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
        app = self.app_with_two_rows()

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
        app = self.app_with_two_rows()

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
        app = self.app_with_two_rows()

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
        # hiding Undo and Quit even though undo is the safety net for a
        # mis-keyed `x`.
        app = self.app_with_two_rows()

        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            screen = app.export_screenshot()

        self.assertIn("Undo", screen)
        self.assertIn("Quit", screen)
        # The filters are ticket 06's contribution to the one line that says
        # what the queue is; they must not push the safety net off it.
        for binding in ("Search", "Family", "Decided", "Clear"):
            self.assertIn(binding, screen)

    # -- filters (ticket 06) -------------------------------------------------

    def build_index_with_families(self):
        # Three families, one of them (unknown); row three mentions "bakery"
        # only in its description, so it is the row a search must NOT match.
        self.build_index([
            _row("one", "Cashier One", company="Bakery Corner", term_label="Retail"),
            _row("two", "Baker Two", company="Example Employer", term_label="Bakery"),
            _row(
                "three", "Dishwasher Three", company="Sunrise Diner",
                term_label="", search_term='"dishwasher"',
                description="Only the description says bakery.",
            ),
        ])

    def titles(self, app):
        """Every title in the queue, in order -- the queue as it stands."""
        table = app.query_one("#queue", DataTable)
        out = []
        for index in range(table.row_count):
            cell = table.get_row_at(index)[0]
            out.append(cell.plain if hasattr(cell, "plain") else str(cell))
        return out

    def header(self, app):
        return str(app.query_one("#filters", Static).render())

    def recent_footer(self, app):
        return str(app.query_one("#recent", Static).render())

    async def test_a_search_term_narrows_to_title_and_company_matches(self):
        # `jobsview search --match` minus FTS: title and company, never the
        # description. Row three says "bakery" only in its description.
        self.build_index_with_families()
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            bar = app.query_one("#search", Input)
            self.assertIs(app.focused, bar, "/ must open the filter bar")
            self.assertTrue(bar.display)

            await type_in_bar(pilot, "bakery")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(
                ["Cashier One"], self.titles(app),
                "the row that says it only in the description is not a match",
            )
            self.assertFalse(bar.display, "Enter closes the bar again")
            self.assertIs(app.focused, app.query_one("#queue", DataTable))
            self.assertIn('title/company="bakery"', self.header(app))

            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(["Cashier One", "Baker Two", "Dishwasher Three"], self.titles(app))
            self.assertEqual(
                "Queue: decision=unreviewed | job family=all | title/company=all",
                self.header(app),
            )

    async def test_search_is_typed_into_the_bar_and_not_the_queue(self):
        # The bar's keys must reach the bar: `j`, `a`, `k` and `space` are
        # queue keys, and a search term is made of exactly those letters.
        self.build_index([
            _row("one", "Cashier One", company="Bakery Corner"),
            _row("two", "Jas Baker", company="Cafe"),
        ])
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            await type_in_bar(pilot, "jas baker")
            await pilot.pause()

            self.assertEqual("jas baker", app.query_one("#search", Input).value)
            self.assertEqual(["Jas Baker"], self.titles(app))
            self.assertEqual(0, app.query_one("#queue", DataTable).cursor_row)
            # The keys never reached the queue: nothing moved, nothing was set.
            state = self.listing()
            first_line = next(line for line in state.splitlines() if "job/one" in line)
            self.assertIn("unreviewed", first_line)
            self.assertIn("none", first_line)

    async def test_family_filter_cycles_the_families_the_queue_offers(self):
        self.build_index_with_families()
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(["Cashier One", "Baker Two", "Dishwasher Three"], self.titles(app))

            await pilot.press("f")
            await pilot.pause()
            self.assertEqual(["Baker Two"], self.titles(app), "first family, alphabetically")
            self.assertIn("job family=Bakery", self.header(app))

            await pilot.press("f")
            await pilot.pause()
            self.assertEqual(["Cashier One"], self.titles(app))
            self.assertIn("job family=Retail", self.header(app))

            # (unknown) is offered last so those rows stay reachable.
            await pilot.press("f")
            await pilot.pause()
            self.assertEqual(["Dishwasher Three"], self.titles(app))
            self.assertIn("job family=(unknown)", self.header(app))

            await pilot.press("f")
            await pilot.pause()
            self.assertEqual(
                ["Cashier One", "Baker Two", "Dishwasher Three"], self.titles(app),
                "the walk ends back on every family",
            )
            self.assertIn("job family=all", self.header(app))

    async def test_the_decision_filter_cycles_to_decided_rows_and_back(self):
        self.build_index([
            _row("one", "Cashier One"),
            _row("two", "Cashier Two"),
            _row("three", "Cashier Three"),
        ])
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            self.assertEqual(["Cashier Two", "Cashier Three"], self.titles(app))

            await pilot.press("d")
            await pilot.pause()
            self.assertEqual(["Cashier One"], self.titles(app))
            self.assertIn("decision=keep", self.header(app))
            self.assertIn("Showing: 1 of 3", str(app.query_one("#counts", Static).render()))

            await pilot.press("d")
            await pilot.pause()
            self.assertEqual([], self.titles(app), "nothing is a false positive yet")

            await pilot.press("d")
            await pilot.pause()
            self.assertEqual(["Cashier One", "Cashier Two", "Cashier Three"], self.titles(app))
            self.assertIn("decision=all", self.header(app))

            await pilot.press("d")
            await pilot.pause()
            self.assertEqual(
                ["Cashier Two", "Cashier Three"], self.titles(app),
                "and back to the opening queue",
            )
            self.assertIn("decision=unreviewed", self.header(app))

    async def test_the_decision_cycle_is_observable_once_decisions_are_shown(self):
        # Ticket 05 recorded that `space`'s cycle could not be seen on an
        # unreviewed-only queue: one press set keep and the row left. With a
        # decision filter, the same row can be cycled twice.
        self.build_index([_row("one", "Cashier One"), _row("two", "Cashier Two")])
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(3):
                await pilot.press("d")  # unreviewed -> keep -> false_positive -> all
            await pilot.pause()
            self.assertEqual(["Cashier One", "Cashier Two"], self.titles(app))

            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(
                ["Cashier One", "Cashier Two"], self.titles(app),
                "a row that gains a decision stays visible on an `all` queue",
            )
            state = self.listing()
            first_line = next(line for line in state.splitlines() if "job/one" in line)
            self.assertIn("keep", first_line)
            self.assertEqual(
                "Cashier Two", self.selected_title(app), "the cursor still advances"
            )

    async def test_filters_combine_and_keep_order_and_the_cursors_row(self):
        self.build_index_with_families()
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("j")
            await pilot.pause()
            self.assertEqual("Baker Two", self.selected_title(app))

            # A conjunction: a term that matches two of the three rows, and
            # a family filter that takes one of those two away.
            await pilot.press("/")
            await pilot.pause()
            await type_in_bar(pilot, "bake")
            await pilot.press("enter")  # close the bar; `f` is a queue key
            await pilot.pause()
            self.assertEqual(
                ["Cashier One", "Baker Two"], self.titles(app),
                "the term narrows by title or company, never by description",
            )
            self.assertEqual("Baker Two", self.selected_title(app))

            await pilot.press("f")
            await pilot.pause()
            self.assertEqual(["Baker Two"], self.titles(app))
            self.assertIn("job family=Bakery", self.header(app))
            self.assertEqual(
                "Baker Two", self.selected_title(app),
                "the cursor keeps its row while that row is still visible",
            )

            # A term that drops the cursor's row keeps its position instead.
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(
                ["Cashier One", "Baker Two", "Dishwasher Three"], self.titles(app),
                "Escape clears the family filter too",
            )
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            await type_in_bar(pilot, "cashier one")
            await pilot.pause()
            self.assertEqual(["Cashier One"], self.titles(app))
            self.assertEqual(
                "Cashier One", self.selected_title(app),
                "a row that leaves the queue leaves its position behind",
            )


    async def test_escape_does_not_quit_and_q_quits(self):
        app = self.app_with_two_rows()

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertTrue(app.is_running)

            await pilot.press("escape")
            await pilot.pause()
            self.assertTrue(app.is_running, "Escape should be safe to press reflexively")

            await pilot.press("q")
            await pilot.pause()
            self.assertFalse(app.is_running)

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

            await pilot.press("x")
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

    async def test_a_search_term_of_console_markup_renders_literally(self):
        # The search bar takes arbitrary typing, and a `[` `]` pair reaches the
        # header. Textual parses plain strings as console markup, so `[/]`
        # raised MarkupError inside the keystroke handler and `[foo]bar` was
        # silently displayed as "bar". Both are the same one-line bug.
        self.build_index([
            _row("one", "Cashier One", company="Bakery Corner"),
            _row("two", "Baker Two"),
        ])
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            for character in "[/]":
                await pilot.press(character)
                await pilot.pause()
            self.assertEqual(
                'Queue: decision=unreviewed | job family=all | title/company="[/]"',
                self.header(app),
                "a term is text, never markup: no error, nothing swallowed",
            )
            await pilot.press("backspace")
            await pilot.pause()
            for character in "foo]bar":
                await pilot.press(character)
                await pilot.pause()
            self.assertIn('title/company="[/foo]bar"', self.header(app))

    async def test_a_job_title_of_console_markup_renders_literally(self):
        # The other side of the same bug: titles come out of the index, and
        # DataTable parsed str cells as markup, so one hostile row took the
        # whole table down with a MarkupError.
        self.build_index([
            _row("one", "Cashier[/red] One"),
            _row("two", "Cashier Two"),
        ])
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(
                ["Cashier[/red] One", "Cashier Two"],
                self.titles(app),
                "the title reaches the screen byte for byte",
            )

    async def test_undo_of_a_row_the_filter_now_hides_says_so(self):
        # Restoring `unreviewed` while the queue is filtered to `keep` leaves
        # the row outside it. The status bar announced the undo and the row
        # vanished anyway -- indistinguishable from losing a good job.
        self.build_index([
            _row("one", "Cashier One"),
            _row("two", "Cashier Two"),
        ])
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("y")      # keep row one, on the unreviewed filter
            await pilot.pause()
            self.assertEqual(1, app.query_one("#queue", DataTable).row_count)

            await pilot.press("d")      # filter to decision=keep
            await pilot.pause()
            self.assertEqual(["Cashier One"], self.titles(app))

            await pilot.press("ctrl+z")  # undo -> unreviewed, outside the filter
            await pilot.pause()
            self.assertEqual(0, app.query_one("#queue", DataTable).row_count)
            self.assertIn(
                "hidden by decision=keep; Esc clears it",
                str(app.query_one("#undo-status", Static).render()),
                "name the filter that hid the row, and the key that reveals it",
            )

    async def test_the_undo_note_names_the_filter_that_actually_hid_the_row(self):
        # The note blamed `decision=<filter>` for whatever hid the row, so a
        # family or search filter got the decision filter's name. Note that a
        # row in the queue before the undo only leaves by a filter that moved
        # *after* the decision was set -- otherwise the undo restores exactly
        # what the filter already admits, and the note must stay silent.
        self.build_index_with_families()
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(
                ["Cashier One", "Baker Two", "Dishwasher Three"], self.titles(app)
            )

            # Readmitted: `keep` -> `unreviewed` on the opening filter keeps the
            # row in the queue, so there is no cause to name.
            await pilot.press("y")
            await pilot.pause()
            await pilot.press("ctrl+z")
            await pilot.pause()
            note = str(app.query_one("#undo-status", Static).render())
            self.assertIn("Undid Cashier One", note)
            self.assertNotIn(
                "hidden by", note, "the row is in the queue: no cause to name"
            )

            # A family filter that moved after the keep. `all` admits every
            # decision, so naming the decision filter here would be wrong.
            await pilot.press("escape")
            for _ in range(3):       # unreviewed -> keep -> false_positive -> all
                await pilot.press("d")
            await pilot.pause()
            self.assertIn("decision=all", self.header(app))
            await pilot.press("f")   # Bakery: only Baker Two stays
            await pilot.pause()
            self.assertEqual(["Baker Two"], self.titles(app))
            await pilot.press("y")   # keep the row the filter already admits
            await pilot.press("f")   # Retail: the kept row is no longer offered
            await pilot.pause()
            self.assertEqual(["Cashier One"], self.titles(app))
            await pilot.press("ctrl+z")  # undo -> unreviewed, and outside Retail
            await pilot.pause()
            note = str(app.query_one("#undo-status", Static).render())
            self.assertNotIn(
                "decision=", note, "the decision filter admits this row now"
            )
            self.assertIn("hidden by job family=Retail; Esc clears it", note)

            # A search term that moved after the keep, which is the case the
            # decision label got wrong most often.
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            bar = app.query_one("#search", Input)
            bar.value = ""            # the bar keeps the previous term
            await type_in_bar(pilot, "cashier")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(["Cashier One"], self.titles(app))
            await pilot.press("y")    # keep Cashier One under that term
            await pilot.pause()

            await pilot.press("/")    # and a second term in the same bar
            await pilot.pause()
            bar.value = ""
            await type_in_bar(pilot, "dishwasher")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+z")
            await pilot.pause()
            note = str(app.query_one("#undo-status", Static).render())
            self.assertIn(
                'hidden by title/company="dishwasher"',
                note,
                "the search term is named, not the decision filter",
            )
            self.assertIn("; Esc clears it", note)

    async def test_the_recent_footer_renders_a_hostile_title_literally(self):
        # The third footer had no guard at all: `Recent` prints the last three
        # titles straight out of the index, and nothing pinned that a title
        # holding `[/red]` arrives on screen as itself. This is the label whose
        # content comes from the same untrusted place as the queue cells, so it
        # is written as `Text` for the same reason they are.
        self.build_index([
            _row("one", "Cashier[/red] One"),
            _row("two", "Cashier Two"),
        ])
        app = ReviewBenchApp(self.args)

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual("Recent: none", self.recent_footer(app))

            await pilot.press("y")
            await pilot.pause()
            self.assertIn(
                "Cashier[/red] One: keep / none", self.recent_footer(app),
                "a title is text, never markup",
            )

class ExportTest(unittest.TestCase):
    """Survivors CSV export (ticket 07): one code path for the CLI and the bench."""

    EXPORT_COLUMNS = jobsview.EXPORT_COLUMNS

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.db = self.data / "jobs.db"
        self.queries = self.data / "queries.txt"
        self.queries.write_text('# --- Retail ---\n"cashier"\n', encoding="utf-8")

    def build_index(self, rows):
        with (self.data / "jobs_0.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        args = argparse.Namespace(
            data_dir=str(self.data), db=str(self.db), queries=str(self.queries),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, jobsview.cmd_ingest(args))
        return args

    def run_export(self, args, output):
        args2 = argparse.Namespace(**vars(args), output=str(output))
        with contextlib.redirect_stdout(io.StringIO()):
            return jobsview.cmd_export(args2)

    def test_export_writes_exact_header_and_only_kept_rows(self):
        rows = [
            _row("one", "Cashier One"),
            _row("two", "Cashier Two"),
            _row("three", "Cashier Three"),
        ]
        args = self.build_index(rows)
        # keep one, false_positive one, leave one unreviewed
        con = jobsview._review_db(args)
        try:
            jobsview.set_decision(con, "https://indeed.com/job/one", "keep")
            jobsview.set_decision(con, "https://indeed.com/job/two", "false_positive")
            jobsview.set_application_status(con, "https://indeed.com/job/one", "applied")
        finally:
            con.close()

        output = self.data / "survivors.csv"
        self.assertEqual(0, self.run_export(args, output))
        with output.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            data_rows = list(reader)
        self.assertEqual(list(self.EXPORT_COLUMNS), header)
        self.assertEqual(1, len(data_rows))
        kept = data_rows[0]
        self.assertEqual("https://employer.example/jobs/one", kept[0])
        self.assertEqual("Cashier One", kept[1])
        self.assertEqual("keep", kept[10])
        self.assertEqual("applied", kept[11])
        self.assertEqual("stamped", kept[9])

    def test_rerun_drops_a_rejected_row(self):
        rows = [_row("one", "Cashier One"), _row("two", "Cashier Two")]
        args = self.build_index(rows)
        con = jobsview._review_db(args)
        try:
            jobsview.set_decision(con, "https://indeed.com/job/one", "keep")
            jobsview.set_decision(con, "https://indeed.com/job/two", "keep")
        finally:
            con.close()

        output = self.data / "survivors.csv"
        self.run_export(args, output)
        # reject one between runs
        con = jobsview._review_db(args)
        try:
            jobsview.set_decision(con, "https://indeed.com/job/two", "false_positive")
        finally:
            con.close()
        self.run_export(args, output)
        with output.open(newline="", encoding="utf-8") as fh:
            lines = list(csv.reader(fh))
        self.assertEqual(2, len(lines))  # header + one row
        self.assertEqual("Cashier One", lines[1][1])

    def test_all_rejected_writes_header_only(self):
        args = self.build_index([_row("one", "Cashier One")])
        output = self.data / "survivors.csv"
        self.run_export(args, output)
        self.assertTrue(output.is_file())
        with output.open(newline="", encoding="utf-8") as fh:
            content = fh.read()
        self.assertEqual(",".join(self.EXPORT_COLUMNS) + "\n", content)

    def test_export_orders_by_date_posted_desc(self):
        rows = [
            _row("a", "Older", date_posted="2026-01-01"),
            _row("b", "Newer", date_posted="2026-02-02"),
        ]
        args = self.build_index(rows)
        con = jobsview._review_db(args)
        try:
            for url in ("https://indeed.com/job/a", "https://indeed.com/job/b"):
                jobsview.set_decision(con, url, "keep")
        finally:
            con.close()
        output = self.data / "survivors.csv"
        self.run_export(args, output)
        with output.open(newline="", encoding="utf-8") as fh:
            titles = [r[1] for r in csv.reader(fh) if r and r[1] != "title"]
        self.assertEqual(["Newer", "Older"], titles)


    def test_export_runs_headless_via_subprocess(self):
        args = self.build_index([_row("one", "Cashier One")])
        con = jobsview._review_db(args)
        try:
            jobsview.set_decision(con, "https://indeed.com/job/one", "keep")
        finally:
            con.close()
        output = self.data / "survivors.csv"
        proc = subprocess.run(
            [sys.executable, "-S", str(JOBSVIEW),
             "--data-dir", str(self.data), "--db", str(self.db),
             "--queries", str(self.queries),
             "export", "--output", str(output)],
            cwd=str(self.data), capture_output=True, text=True,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("1 kept job(s)", proc.stdout)
        self.assertTrue(output.is_file())

    @BENCH
    async def test_tui_export_byte_identical_to_cli(self):
        # The bench shells out to the same export, so the files must match.
        self.build_index([_row("one", "Cashier One"), _row("two", "Cashier Two")])
        args = argparse.Namespace(
            data_dir=str(self.data), db=str(self.db), queries=str(self.queries),
        )
        con = jobsview._review_db(args)
        try:
            jobsview.set_decision(con, "https://indeed.com/job/one", "keep")
        finally:
            con.close()
        cli_output = self.data / "cli.csv"
        with contextlib.redirect_stdout(io.StringIO()):
            jobsview.cmd_export(argparse.Namespace(**vars(args), output=str(cli_output)))
        app = ReviewBenchApp(args)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
        tui_output = self.data / "survivors.csv"
        self.assertTrue(tui_output.is_file())
        self.assertEqual(cli_output.read_bytes(), tui_output.read_bytes())


class KanbanTest(unittest.TestCase):
    """Kanban.md export (ticket 08): temp paths only, never the default board."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.db = self.data / "jobs.db"
        self.queries = self.data / "queries.txt"
        self.queries.write_text('# --- Retail ---\n"cashier"\n', encoding="utf-8")
        self.board = self.data / "kanban.md"

    def build_index(self, rows):
        with (self.data / "jobs_0.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        args = argparse.Namespace(
            data_dir=str(self.data), db=str(self.db), queries=str(self.queries),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, jobsview.cmd_ingest(args))
        return args

    def run_kanban(self, args):
        a = argparse.Namespace(**vars(args), kanban=str(self.board))
        with contextlib.redirect_stdout(io.StringIO()):
            return jobsview.cmd_kanban(a)

    def test_custom_settings_block_is_preserved(self):
        rows = [_row("a", "Kept")]
        args = self.build_index(rows)
        con = jobsview._review_db(args)
        try:
            jobsview.set_decision(con, "https://indeed.com/job/a", "keep")
        finally:
            con.close()
        # pre-existing board with a custom settings line
        custom = (
            "---\n\nkanban-plugin: basic\n\n---\n\n"
            "## Interested\n\n- [ ] old\n\n"
            "%% kanban:settings\n```\n"
            '{"kanban-plugin":"basic","lane-width":320}\n'
            "```\n%%\n"
        )
        self.board.write_text(custom, encoding="utf-8")
        self.run_kanban(args)
        out = self.board.read_text(encoding="utf-8")
        self.assertIn('"lane-width":320', out)
        self.assertIn("Kept", out)

    def test_one_row_per_status_produces_six_sections(self):
        rows = [_row(str(i), f"Job {i}") for i in range(6)]
        args = self.build_index(rows)
        statuses = ("none", "applied", "interview", "offer", "rejected", "withdrawn")
        con = jobsview._review_db(args)
        try:
            for i, status in enumerate(statuses):
                jobsview.set_decision(con, f"https://indeed.com/job/{i}", "keep")
                jobsview.set_application_status(con, f"https://indeed.com/job/{i}", status)
        finally:
            con.close()
        self.assertEqual(0, self.run_kanban(args))
        text = self.board.read_text(encoding="utf-8")
        for name in ("Interested", "Applied", "Interview", "Offer", "Rejection", "Withdrawn"):
            self.assertIn(f"## {name}", text)
        positions = [text.index(f"## {name}") for name in
                     ("Interested", "Applied", "Interview", "Offer", "Rejection", "Withdrawn")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("- [ ] Job 0 — Example Employer", text)
        self.assertIn("- [ ] Job 5 — Example Employer", text)
        self.assertIn("kanban-plugin: basic", text)
        self.assertIn("%% kanban:settings", text)

    def test_false_positive_and_unreviewed_rows_produce_empty_board(self):
        rows = [_row("a", "Kept"), _row("b", "Rejected"), _row("c", "Pending")]
        args = self.build_index(rows)
        con = jobsview._review_db(args)
        try:
            jobsview.set_decision(con, "https://indeed.com/job/a", "keep")
            jobsview.set_decision(con, "https://indeed.com/job/b", "false_positive")
        finally:
            con.close()
        self.run_kanban(args)
        text = self.board.read_text(encoding="utf-8")
        self.assertIn("Kept", text)
        self.assertNotIn("Rejected", text)
        self.assertNotIn("Pending", text)

    def test_withdrawn_maps_only_to_withdrawn_section(self):
        rows = [_row("a", "Gone")]
        args = self.build_index(rows)
        con = jobsview._review_db(args)
        try:
            jobsview.set_decision(con, "https://indeed.com/job/a", "keep")
            jobsview.set_application_status(con, "https://indeed.com/job/a", "withdrawn")
        finally:
            con.close()
        self.run_kanban(args)
        text = self.board.read_text(encoding="utf-8")
        idx = text.index("- [ ] Gone — Example Employer")
        header = text.rfind("## ", 0, idx)
        self.assertEqual("## Withdrawn", text[header:header + len("## Withdrawn")])

    def test_rerun_moves_card_between_sections(self):
        rows = [_row("a", "Mover")]
        args = self.build_index(rows)
        con = jobsview._review_db(args)
        try:
            jobsview.set_decision(con, "https://indeed.com/job/a", "keep")
            jobsview.set_application_status(con, "https://indeed.com/job/a", "none")
        finally:
            con.close()
        self.run_kanban(args)
        text1 = self.board.read_text(encoding="utf-8")
        self.assertIn("## Interested", text1)
        con = jobsview._review_db(args)
        try:
            jobsview.set_application_status(con, "https://indeed.com/job/a", "applied")
        finally:
            con.close()
        self.run_kanban(args)
        text2 = self.board.read_text(encoding="utf-8")
        self.assertEqual(1, text2.count("- [ ] Mover — Example Employer"))
        idx = text2.index("- [ ] Mover — Example Employer")
        header = text2.rfind("## ", 0, idx)
        self.assertEqual("## Applied", text2[header:header + len("## Applied")])

    def test_kanban_runs_headless_via_subprocess(self):
        rows = [_row("a", "Headless")]
        args = self.build_index(rows)
        con = jobsview._review_db(args)
        try:
            jobsview.set_decision(con, "https://indeed.com/job/a", "keep")
        finally:
            con.close()
        proc = subprocess.run(
            [sys.executable, "-S", str(JOBSVIEW),
             "--data-dir", str(self.data), "--db", str(self.db),
             "--queries", str(self.queries),
             "kanban", "--kanban", str(self.board)],
            cwd=str(self.data), capture_output=True, text=True,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertTrue(self.board.is_file())
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

    def test_search_semantics_stay_stdlib_only(self):
        # The bench's `/` search runs without Textual: it is one predicate
        # over rows already loaded, and its semantics are the CLI's LIKE.
        row = {"title": "Head Baker", "company": "Bakery Corner"}

        self.assertTrue(jobsview.matches_search(row, ""), "no term is no filter")
        self.assertTrue(jobsview.matches_search(row, "bake"))
        self.assertTrue(jobsview.matches_search(row, "BAKERY"), "LIKE is case-insensitive")
        self.assertTrue(jobsview.matches_search(row, "corner"), "company counts")
        self.assertFalse(jobsview.matches_search(row, "dishwasher"))
        self.assertFalse(
            jobsview.matches_search({"title": "Baker", "company": "Acme"}, "baker acme"),
            "one column at a time, never the two concatenated",
        )
        self.assertTrue(jobsview.matches_search(row, "%"), "a bare wildcard matches all")
        self.assertTrue(jobsview.matches_search({"title": "a_b"}, "a_b"), "`_` is one character")
        self.assertFalse(
            jobsview.matches_search({"title": "ab"}, "a_b"), "so it cannot be skipped"
        )
        # ASCII-only folding, exactly like SQLite. Python's IGNORECASE folds
        # all of Unicode, so U+212A (KELVIN SIGN) would otherwise match "k"
        # in the bench while `SELECT 'K' LIKE '%<u212a>%'` returns 0 in the
        # CLI -- the bench would quietly show more rows than the CLI would.
        self.assertFalse(
            jobsview.matches_search({"title": "\u212a"}, "k"),
            "non-ASCII case folding would diverge from SQLite's LIKE",
        )
        self.assertTrue(jobsview.matches_search({"title": "K"}, "k"), "ASCII still folds")

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
