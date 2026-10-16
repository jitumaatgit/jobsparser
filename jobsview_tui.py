"""Textual interface for the jobsview review bench.

Kept separate so importing jobsview's headless commands never imports Textual.
"""
from __future__ import annotations

import webbrowser
from typing import Any

from rich.markdown import Markdown
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Input, RichLog, Static

import jobsview


# The decision filter's states. The bench opens on the unreviewed queue --
# the spec's flat-queue default -- and `d` walks these in order.
DECISION_FILTERS = ("unreviewed", "keep", "false_positive", "all")
ALL_DECISIONS = "all"
DEFAULT_DECISION_FILTER = "unreviewed"

# A row with no family at all: `resolve_family`'s (unknown), offered by the
# family filter so such rows stay reachable instead of being hidden.
UNKNOWN_FAMILY = "(unknown)"

# How much of a search term the header line shows before eliding it.
SEARCH_DISPLAY_LIMIT = 40


def _shorten(text: str, limit: int) -> str:
    """One line's worth of a filter value, elided rather than clipped."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ReviewQueue(DataTable):
    """The queue, which sizes its own columns.

    Textual 8.2.8 has no fractional column widths, so a fixed set of widths
    cannot reflow: widths big enough to read also sum to more cells than an
    ordinary terminal hands the queue, and Textual does not draw the columns
    past that point -- at 140 columns it drew four of the eight, silently
    removing Pay, Job family, Decision and Status, the two axes this screen
    exists to show, with no key that reached them. The table therefore derives
    its widths from the space it really has, and the weights say who squeezes
    first: Title, Company and the axes hold their width, and the columns whose
    full value the detail pane already shows pay for it.

    The resize handler lives here rather than on the App because App defines
    `_on_resize`, which shadows a subclass's `on_resize` -- a handler on the App
    is silently never called.
    """

    COLUMNS = (
        # label, key, width weight, minimum content width
        ("Title", "title", 4, 9),
        ("Company", "company", 4, 7),
        ("Location", "location", 2, 3),
        ("Date", "date", 3, 10),
        ("Pay", "pay", 2, 3),
        ("Job family", "family", 2, 10),
        ("Decision", "decision", 3, 10),
        ("Status", "status", 4, 8),
    )
    TOTAL_WEIGHT = sum(weight for _, _, weight, _ in COLUMNS)
    MIN_WIDTH = 4
    _last_sized_width = 0

    def on_mount(self) -> None:
        for label, key, _weight, _minimum in self.COLUMNS:
            self.add_column(label, key=key, width=self.MIN_WIDTH)

    def on_resize(self, _event: events.Resize) -> None:
        self.distribute_columns()

    def distribute_columns(self) -> None:
        """Size the columns to the width the queue actually has."""
        available = self.size.width
        if available <= 0 or available == self._last_sized_width:
            return
        self._last_sized_width = available
        if len(self.columns) != len(self.COLUMNS):
            return
        padding = 2 * self.cell_padding * len(self.COLUMNS)
        content_width = available - padding
        minimum_width = sum(minimum for _, _, _, minimum in self.COLUMNS)
        extra = max(0, content_width - minimum_width)
        widths = [
            minimum + extra * weight // self.TOTAL_WEIGHT
            for _, _, weight, minimum in self.COLUMNS
        ]
        remainder = extra - sum(
            width - minimum
            for width, (_, _, _, minimum) in zip(widths, self.COLUMNS)
        )
        for index in range(remainder):
            widths[index] += 1
        # If minimums don't fit, retain readable cells and let the user scroll.
        for column, width in zip(self.columns.values(), widths):
            column.width = width
        self.refresh(layout=True)


class ReviewBenchApp(App[None]):
    """Keyboard-driven queue over the derived jobs index and review sidecar."""

    TITLE = "Jobs review bench"
    # The search bar precedes the queue in the DOM, so the default "*" would
    # focus it on startup -- and with the queue's keys disabled while the bar
    # has focus, the bench would open inert. The queue is the opening view.
    AUTO_FOCUS = "#queue"
    BINDINGS = [
        Binding("left", "scroll_queue_left", "Scroll left", show=False, priority=True),
        Binding("right", "scroll_queue_right", "Scroll right", show=False, priority=True),
        Binding("ctrl+k", "scroll_detail_up", "Detail up", show=False, priority=True),
        Binding("ctrl+j", "scroll_detail_down", "Detail down", show=False, priority=True),
        Binding("j", "next_row", "Next", show=True, priority=True),
        Binding("down", "next_row", "Next", show=False, priority=True),
        Binding("k", "previous_row", "Previous", show=True, priority=True),
        Binding("up", "previous_row", "Previous", show=False, priority=True),
        Binding("enter", "show_detail", "Details", show=True, priority=True),
        Binding("v", "open_job", "Open URL", show=True, priority=True),
        Binding("space", "cycle_decision", "Decision", show=True, priority=True),
        Binding("y", "keep", "Keep", show=False, priority=True),
        # `f` narrows the queue to one job family, so the direct false-positive
        # key moves to `x`: `space` still cycles all three decisions, but a
        # long session needs a one-press reject.
        Binding("x", "false_positive", "False positive", show=False, priority=True),
        Binding("u", "unreviewed", "Unreviewed", show=False, priority=True),
        # The filters get one footer slot each: a queue narrowed by `/`, `f`
        # or `d` must never be mistakable for the whole set, and the way back
        # (`escape`) is only useful while it is visible.
        Binding("/", "search", "Search", show=True, priority=True),
        Binding("f", "cycle_family", "Family", show=True, priority=True),
        Binding("d", "cycle_decision_filter", "Decided", show=True, priority=True),
        Binding("escape", "clear_filters", "Clear", show=True, priority=True),
        # One key per application status, but not one footer slot each: sixteen
        # shown bindings run past a 140-column footer, which silently dropped
        # Withdrawn, None, Undo and Quit off the right-hand end. Undo is the
        # safety net for a mis-keyed `f`, so the keys keep working and the
        # footer keeps the bindings that protect the session instead.
        Binding("a", "applied", "Applied", show=False, priority=True),
        Binding("i", "interview", "Interview", show=False, priority=True),
        Binding("o", "offer", "Offer", show=False, priority=True),
        Binding("r", "rejected", "Rejected", show=False, priority=True),
        Binding("w", "withdrawn", "Withdrawn", show=False, priority=True),
        Binding("0", "none", "None", show=False, priority=True),
        Binding("n", "none", "None", show=False, priority=True),
        Binding("ctrl+z", "undo", "Undo", show=True, priority=True),
        Binding("q", "quit", "Quit", show=True, priority=True),
    ]
    DEFAULT_CSS = """
    Screen { layout: vertical; }
    #filters { height: 1; padding: 0 1; background: $panel; }
    #search { display: none; height: 1; border: none; padding: 0 1; background: $panel; }
    #workspace { height: 1fr; }
    #queue { width: 3fr; height: 1fr; }
    #description { width: 2fr; height: 1fr; border: round $border; padding: 0 1; }
    #description:focus { border: round $accent; }
    #counts, #undo-status, #recent { height: 1; padding: 0 1; }
    #undo-status { color: $text; }
    #recent { color: $text-muted; }
    """

    def __init__(self, args: Any) -> None:
        super().__init__()
        self.args = args
        self._rows: list[dict[str, Any]] = []
        self._rows_by_url: dict[str, dict[str, Any]] = {}
        self._queue: list[dict[str, Any]] = []
        # Active filters, as a conjunction. The decision filter opens on the
        # spec's flat queue: unreviewed rows only.
        self._search = ""
        self._family_filter: str | None = None
        self._decision_filter = DEFAULT_DECISION_FILTER
        self._search_bar: Input | None = None
        self._undo_stack: list[tuple[str, str, str]] = []
        self._recent: list[tuple[str, str, str]] = []

    def compose(self) -> ComposeResult:
        # Every Static here renders text that is either typed by the user (the
        # search term) or read out of the index (a job title). Both are
        # untrusted: a `[`, `]` or `[/]` in either is parsed as console markup
        # and either raises MarkupError or silently eats the text. markup=False
        # renders exactly what was given, so a term stays a term.
        yield Static(self._filters_text(), id="filters", markup=False)
        # The bar is opened by `/` and closed again on Enter: a permanent
        # extra row would cost a line of an already tight screen, and the
        # header keeps the active term visible while it is closed.
        self._search_bar = Input(
            id="search",
            placeholder="title or company — Enter closes, Esc clears",
            compact=True,
        )
        yield self._search_bar
        with Horizontal(id="workspace"):
            # The minimum column widths preserve readable cell boundaries;
            # at a very narrow queue they intentionally overflow and scroll.
            yield ReviewQueue(
                id="queue", cursor_type="row", zebra_stripes=True, cell_padding=1,
            )
            yield RichLog(id="description", wrap=True, markup=False)
        yield Static(id="counts", markup=False)
        yield Static(
            "Ready — / search, f family, d decision, Esc clear; Ctrl-Z undoes.",
            id="undo-status", markup=False,
        )
        yield Static("Recent: none", id="recent", markup=False)
        yield Footer(compact=True)

    def on_mount(self) -> None:
        self._reload_queue()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        """Disable the queue's keys while the search bar is being typed into.

        A priority binding is checked before the focused widget sees the key,
        so without this every letter of a search term would drive the queue
        instead of the bar. Escape is the exception: it cannot be typed, and
        it is the way out of the bar and out of the filters.

        `run_action` reads this as a plain truth value -- a `None` would
        disable the very actions it was meant to leave alone -- so the answer
        is always a bool.
        """
        if self.focused is self._search_bar:
            return action == "clear_filters"
        return True

    def on_input_changed(self, event: Input.Changed) -> None:
        """Narrow as the term is typed -- nothing waits for confirmation."""
        self._search = event.value
        self._apply_filters()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._close_search()

    def _close_search(self) -> None:
        """Hand focus back to the queue before the bar is hidden."""
        if self._search_bar is None:
            return
        self.query_one("#queue", DataTable).focus()
        self._search_bar.display = False

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "queue":
            self._show_detail(event.cursor_row)

    def _read_rows(self) -> list[dict[str, Any]]:
        con = jobsview._review_db(self.args)
        try:
            return [dict(row) for row in jobsview._review_rows(con, self.args.db)]
        finally:
            con.close()

    @staticmethod
    def _decision(row: dict[str, Any]) -> str:
        return row.get("decision") or "unreviewed"

    @staticmethod
    def _status(row: dict[str, Any]) -> str:
        return row.get("application_status") or "none"

    def _display_row(self, row: dict[str, Any]) -> tuple[Text, ...]:
        # `Text`, not `str`: DataTable parses plain strings as console markup,
        # so one title carrying `[/red]` took the whole table down. A Text cell
        # reaches the renderer untouched.
        return (
            Text(row.get("title") or ""),
            Text(row.get("company") or ""),
            Text(row.get("location") or ""),
            Text((row.get("date_posted") or "")[:10]),
            Text(jobsview._pay_label(row)),
            Text(jobsview._family_label(row)),
            Text(self._decision(row)),
            Text(self._status(row)),
        )

    # -- filters ------------------------------------------------------------
    #
    # Applied to the rows already loaded, never by re-querying SQLite: the
    # queue keeps its index order and the cursor keeps its row across a
    # narrowing, so a filter is something you try and step back out of.

    @staticmethod
    def _raw_family(row: dict[str, Any]) -> str:
        """The family as the filter sees it: (unknown) when there is none.

        The family column flags a guess with "(inferred)", but the filter
        must not split one family into a recorded and a guessed half.
        """
        return row.get("job_family") or UNKNOWN_FAMILY

    def _matches_decision(self, row: dict[str, Any]) -> bool:
        return (
            self._decision_filter == ALL_DECISIONS
            or self._decision(row) == self._decision_filter
        )

    def _in_queue(self, row: dict[str, Any]) -> bool:
        """One row against the active filters, as a conjunction."""
        return (
            self._matches_decision(row)
            and (self._family_filter is None or self._raw_family(row) == self._family_filter)
            and jobsview.matches_search(row, self._search)
        )

    def _hiding_filters(self, row: dict[str, Any]) -> list[str]:
        """Name every active filter this row fails, as `_filters_text` does.

        A row can be outside the queue by one filter, two, or all three, so a
        note that guesses which one is the wrong note. `not _in_queue` only
        says that something hid it.
        """
        hiding = []
        if not self._matches_decision(row):
            hiding.append(f"decision={self._decision_filter}")
        if self._family_filter is not None and self._raw_family(row) != self._family_filter:
            hiding.append(f"job family={self._family_filter}")
        if self._search and not jobsview.matches_search(row, self._search):
            hiding.append(
                f'title/company="{_shorten(self._search, SEARCH_DISPLAY_LIMIT)}"'
            )
        return hiding

    def _family_options(self) -> list[str]:
        """The families the other filters leave, alphabetically, unknown last."""
        rows = [
            row for row in self._rows
            if self._matches_decision(row) and jobsview.matches_search(row, self._search)
        ]
        families = {self._raw_family(row) for row in rows}
        return sorted(families, key=lambda family: (family == UNKNOWN_FAMILY, family))

    def _row_at(self, index: int) -> dict[str, Any] | None:
        if 0 <= index < len(self._queue):
            return self._queue[index]
        return None

    def _fill_table(self, keep_url: str | None = None, position: int = 0) -> None:
        """Rebuild the queue table from the rows the filters leave.

        A filter change is rare, so this is the one place the table is rebuilt
        rather than touched row by row. The cursor follows its own row while
        that row survives, and otherwise keeps its position, so narrowing a
        queue never moves the view out from under the user.
        """
        table = self.query_one("#queue", DataTable)
        self._queue = [row for row in self._rows if self._in_queue(row)]
        table.clear()
        for row in self._queue:
            table.add_row(*self._display_row(row), key=row["job_url"])
        if not self._queue:
            self._show_detail(None)
            return
        index = next(
            (i for i, row in enumerate(self._queue) if row["job_url"] == keep_url),
            position,
        )
        self._place_cursor(table, min(max(index, 0), len(self._queue) - 1))

    def _apply_filters(self) -> None:
        """Re-narrow the queue, keeping the cursor where it was."""
        table = self.query_one("#queue", DataTable)
        position = table.cursor_row or 0
        row = self._row_at(position)
        self._fill_table(
            keep_url=row["job_url"] if row else None,
            position=position,
        )
        self._update_counts()
        self._update_filters()

    def _filters_text(self) -> str:
        """Every active filter, so a narrowed queue is never read as the set."""
        term = self._search.strip()
        search = f'"{_shorten(term, SEARCH_DISPLAY_LIMIT)}"' if term else "all"
        return (
            f"Queue: decision={self._decision_filter} | "
            f"job family={self._family_filter or 'all'} | "
            f"title/company={search}"
        )

    def _update_filters(self) -> None:
        self.query_one("#filters", Static).update(self._filters_text())

    def _announce_filters(self) -> None:
        """Say what the queue now is, and which keys change it."""
        self.query_one("#undo-status", Static).update(
            f"{self._filters_text()} — f family, d decision, / search, Esc clear"
        )

    def _reload_queue(self, selected_url: str | None = None) -> None:
        self._rows = self._read_rows()
        self._rows_by_url = {row["job_url"]: row for row in self._rows}
        self._fill_table(keep_url=selected_url)
        self._update_counts()
        self._update_recent()
        self._update_filters()

    def _update_counts(self) -> None:
        # Counted over every row the index holds, not over the filtered queue:
        # "unreviewed remaining" is a fact about the work left, and the queue
        # size is the `Showing` half.
        unreviewed = sum(self._decision(row) == "unreviewed" for row in self._rows)
        kept = sum(self._decision(row) == "keep" for row in self._rows)
        false_positives = sum(
            self._decision(row) == "false_positive" for row in self._rows
        )
        self.query_one("#counts", Static).update(
            f"Unreviewed remaining: {unreviewed}  |  Kept: {kept}  |  "
            f"False positives: {false_positives}  |  "
            f"Showing: {len(self._queue)} of {len(self._rows)}"
        )

    def _update_recent(self) -> None:
        # `Text`, like the queue cells: a recent title comes out of the index, so
        # the string handed this widget is not this app's to trust. The widget
        # is declared markup=False, which already renders it literally -- this
        # makes the three footer write paths alike, so the next one added cannot
        # be the only one that forgets.
        recent = []
        for job_url, decision, status in reversed(self._recent[-3:]):
            row = self._rows_by_url.get(job_url, {})
            title = row.get("title") or job_url
            recent.append(f"{title}: {decision} / {status}")
        text = Text("Recent: " + ("; ".join(recent) if recent else "none"))
        self.query_one("#recent", Static).update(text)

    def _show_detail(self, index: int | None) -> None:
        detail = self.query_one("#description", RichLog)
        detail.clear()
        if index is None or index < 0 or index >= len(self._queue):
            detail.write("No rows in the current queue.")
            return
        row = self._queue[index]
        direct_url = row.get("job_url_direct") or ""
        job_url = row.get("job_url") or ""
        family = jobsview._family_label(row)
        description = row.get("description") or "(No description provided.)"
        text = (
            f"# {row.get('title') or '(untitled result)'}\n\n"
            f"**Company:** {row.get('company') or '—'}  \n"
            f"**Location:** {row.get('location') or '—'}  \n"
            f"**Date:** {row.get('date_posted') or '—'}  \n"
            f"**Pay:** {jobsview._pay_label(row)}  \n"
            f"**Job family:** {family}  \n"
            f"**Provenance:** {row.get('job_family_source') or 'unknown'}  \n"
            f"**Search term:** {row.get('search_term') or '—'}  \n"
            f"**Term label:** {row.get('term_label') or '—'}  \n"
            f"**Direct URL:** {direct_url or '—'}  \n"
            f"**Job URL:** {job_url}\n\n---\n\n{description}"
        )
        detail.write(Markdown(text))

    def _current(self) -> dict[str, Any] | None:
        if not self._queue:
            return None
        table = self.query_one("#queue", DataTable)
        index = table.cursor_row
        if index is None or index >= len(self._queue):
            return None
        return self._queue[index]

    def _move(self, offset: int) -> None:
        if not self._queue:
            return
        table = self.query_one("#queue", DataTable)
        current = table.cursor_row or 0
        target = max(0, min(len(self._queue) - 1, current + offset))
        self._place_cursor(table, target)

    def _place_cursor(self, table: DataTable, index: int) -> None:
        """Move the cursor, repainting the detail pane exactly once.

        `move_cursor` fires RowHighlighted, which repaints the pane; calling
        `_show_detail` here as well would render the markdown twice per
        keystroke. When the cursor does not actually move, the event does not
        fire, so the pane is repainted explicitly.
        """
        if index == (table.cursor_row or 0):
            self._show_detail(index)
            return
        table.move_cursor(row=index, column=0)

    def action_next_row(self) -> None:
        self._move(1)

    def action_previous_row(self) -> None:
        self._move(-1)

    def action_scroll_queue_left(self) -> None:
        self.query_one("#queue", ReviewQueue).scroll_left(animate=False, force=True)

    def action_scroll_queue_right(self) -> None:
        self.query_one("#queue", ReviewQueue).scroll_right(animate=False, force=True)

    def action_scroll_detail_up(self) -> None:
        self.query_one("#description", RichLog).scroll_up(animate=False)

    def action_scroll_detail_down(self) -> None:
        self.query_one("#description", RichLog).scroll_down(animate=False)

    def action_show_detail(self) -> None:
        """Toggle keyboard focus; the detail pane remains visible."""
        table = self.query_one("#queue", ReviewQueue)
        detail = self.query_one("#description", RichLog)
        self.set_focus(table if self.focused is detail else detail)

    def action_open_job(self) -> None:
        row = self._current()
        if row is None:
            return
        webbrowser.open(row.get("job_url_direct") or row.get("job_url") or "")

    def _write_state(self, job_url: str, decision: str, status: str) -> None:
        con = jobsview._review_db(self.args)
        try:
            jobsview.set_decision(con, job_url, decision)
            jobsview.set_application_status(con, job_url, status)
        finally:
            con.close()

    def _refresh_row(self, row: dict[str, Any]) -> None:
        """Re-point the three cells a decision or status can change.

        Literal `Text` for the same reason `_display_row` uses it: these cells
        are rewritten in place, and a str would be re-parsed as markup.
        """
        table = self.query_one("#queue", DataTable)
        table.update_cell(row["job_url"], "decision", Text(self._decision(row)))
        table.update_cell(row["job_url"], "status", Text(self._status(row)))
        table.update_cell(row["job_url"], "family", Text(jobsview._family_label(row)))

    def _advance_to(self, index: int) -> None:
        """Put the cursor on the row now at `index`, repainting once."""
        table = self.query_one("#queue", DataTable)
        if not self._queue:
            self._show_detail(None)
            return
        self._place_cursor(table, max(0, min(len(self._queue) - 1, index)))

    def _persist_action(self, decision: str | None = None, status: str | None = None) -> None:
        """Write the store, keep the table in step, and advance.

        Only the acted row is touched: a decision removes it from the
        unreviewed queue, a status change repaints it in place. Rebuilding the
        whole table per keystroke would make a long queue feel slow, which is
        the one thing the bench exists to avoid.
        """
        row = self._current()
        if row is None:
            return
        table = self.query_one("#queue", DataTable)
        job_url = row["job_url"]
        index = table.cursor_row or 0
        old_decision = self._decision(row)
        old_status = self._status(row)
        new_decision = decision if decision is not None else old_decision
        new_status = status if status is not None else old_status
        if (new_decision, new_status) == (old_decision, old_status):
            # A key that changes nothing is still an action: advance rather than
            # leaving the cursor where it was, and write no pointless store row.
            self._advance_to(index + 1)
            self.query_one("#undo-status", Static).update(
                f"{row.get('title') or job_url} was already "
                f"{new_decision}/{new_status}"
            )
            self.set_focus(table)
            return
        self._undo_stack.append((job_url, old_decision, old_status))
        self._write_state(job_url, new_decision, new_status)
        self._recent.append((job_url, new_decision, new_status))
        row["decision"], row["application_status"] = new_decision, new_status
        # Whether the acted row is still in the queue is now the filters'
        # question, not the decision's: on a `keep` or `all` queue a row that
        # gains a decision stays visible and is repainted, which is also what
        # makes `space`'s three-state cycle observable at all.
        stays_queued = self._in_queue(row)
        if stays_queued:
            self._refresh_row(row)
        else:
            self._queue.remove(row)
            table.remove_row(job_url)
        self._advance_to(index + (1 if stays_queued else 0))
        self._update_counts()
        self._update_recent()
        self.query_one("#undo-status", Static).update(
            f"Updated {row.get('title') or job_url}: "
            f"{old_decision}/{old_status} → {new_decision}/{new_status}"
        )
        self.set_focus(table)

    def action_cycle_decision(self) -> None:
        row = self._current()
        if row is None:
            return
        current = self._decision(row)
        next_value = jobsview.DECISIONS[(jobsview.DECISIONS.index(current) + 1) % len(jobsview.DECISIONS)]
        self._persist_action(decision=next_value)

    def action_keep(self) -> None:
        self._persist_action(decision="keep")

    def action_false_positive(self) -> None:
        self._persist_action(decision="false_positive")

    def action_unreviewed(self) -> None:
        self._persist_action(decision="unreviewed")

    def action_search(self) -> None:
        """Open the filter bar. The header keeps the term visible when closed."""
        if self._search_bar is not None:
            self._search_bar.display = True
            self._search_bar.focus()

    def action_cycle_family(self) -> None:
        """`f` walks the families the queue offers, then back to all of them."""
        options = self._family_options()
        if not options:
            return
        if self._family_filter in options:
            position = options.index(self._family_filter) + 1
        else:
            position = 0
        self._family_filter = options[position] if position < len(options) else None
        self._apply_filters()
        self._announce_filters()

    def action_cycle_decision_filter(self) -> None:
        self._decision_filter = DECISION_FILTERS[
            (DECISION_FILTERS.index(self._decision_filter) + 1) % len(DECISION_FILTERS)
        ]
        self._apply_filters()
        self._announce_filters()

    def action_clear_filters(self) -> None:
        """Back to the opening queue: every filter off, nothing re-queried."""
        self._search = ""
        if self._search_bar is not None and self._search_bar.value:
            # Posts Changed, which re-applies an empty term -- harmless.
            self._search_bar.value = ""
        self._family_filter = None
        self._decision_filter = DEFAULT_DECISION_FILTER
        self._close_search()
        self._apply_filters()
        self.query_one("#undo-status", Static).update(
            "Filters cleared — the queue is every unreviewed row again."
        )


    def action_applied(self) -> None:
        self._persist_action(status="applied")

    def action_interview(self) -> None:
        self._persist_action(status="interview")

    def action_offer(self) -> None:
        self._persist_action(status="offer")

    def action_rejected(self) -> None:
        self._persist_action(status="rejected")

    def action_withdrawn(self) -> None:
        self._persist_action(status="withdrawn")

    def action_none(self) -> None:
        self._persist_action(status="none")

    def action_undo(self) -> None:
        while self._undo_stack:
            job_url, previous_decision, previous_status = self._undo_stack.pop()
            row = self._rows_by_url.get(job_url)
            if row is None:
                continue  # the row is no longer in the index; nothing to restore
            current_decision = self._decision(row)
            current_status = self._status(row)
            self._write_state(job_url, previous_decision, previous_status)
            row["decision"] = previous_decision
            row["application_status"] = previous_status
            self._recent.append((job_url, previous_decision, previous_status))
            title = row.get("title") or job_url
            self._reload_queue(selected_url=job_url)
            # The restore is applied to the filters too: `keep` -> `unreviewed`
            # under a `keep` filter leaves the row outside the queue. Saying so
            # is the minimum, because "I undid it and it vanished" reads as a
            # lost job.
            #
            # Esc is the reveal that always works: `d` walks the decision
            # filter's cycle, so one press from `keep` lands on
            # `false_positive` -- still hiding an unreviewed row -- and it does
            # nothing at all for a family or search filter.
            hiding = self._hiding_filters(row)
            note = (
                f" — not in the queue: hidden by {', '.join(hiding)}; Esc clears it"
                if hiding
                else ""
            )
            self.query_one("#undo-status", Static).update(
                f"Undid {title}: {current_decision}/{current_status} → "
                f"{previous_decision}/{previous_status}{note}"
            )
            self.set_focus(self.query_one("#queue", DataTable))
            return
