"""Textual interface for the jobsview review bench.

Kept separate so importing jobsview's headless commands never imports Textual.
"""
from __future__ import annotations

import webbrowser
from typing import Any

from rich.markdown import Markdown
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, RichLog, Static

import jobsview


class ReviewBenchApp(App[None]):
    """Keyboard-driven queue over the derived jobs index and review sidecar."""

    TITLE = "Jobs review bench"
    BINDINGS = [
        Binding("j", "next_row", "Next", show=True, priority=True),
        Binding("down", "next_row", "Next", show=False, priority=True),
        Binding("k", "previous_row", "Previous", show=True, priority=True),
        Binding("up", "previous_row", "Previous", show=False, priority=True),
        Binding("enter", "show_detail", "Details", show=True, priority=True),
        Binding("v", "open_job", "Open URL", show=True, priority=True),
        Binding("space", "cycle_decision", "Decision", show=True, priority=True),
        Binding("y", "keep", "Keep", show=True, priority=True),
        Binding("f", "false_positive", "False positive", show=True, priority=True),
        Binding("u", "unreviewed", "Unreviewed", show=False, priority=True),
        Binding("a", "applied", "Applied", show=True, priority=True),
        Binding("i", "interview", "Interview", show=True, priority=True),
        Binding("o", "offer", "Offer", show=True, priority=True),
        Binding("r", "rejected", "Rejected", show=True, priority=True),
        Binding("w", "withdrawn", "Withdrawn", show=True, priority=True),
        Binding("0", "none", "None", show=True, priority=True),
        Binding("n", "none", "None", show=False, priority=True),
        Binding("ctrl+z", "undo", "Undo", show=True, priority=True),
        Binding("escape", "quit", "Quit", show=True),
        Binding("q", "quit", "Quit", show=False),
    ]

    DEFAULT_CSS = """
    Screen { layout: vertical; }
    #filters { height: 1; padding: 0 1; background: $panel; }
    #workspace { height: 1fr; }
    #queue { width: 3fr; height: 1fr; }
    #description { width: 2fr; height: 1fr; border: round $accent; padding: 0 1; }
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
        self._undo_stack: list[tuple[str, str, str]] = []
        self._recent: list[tuple[str, str, str]] = []

    def compose(self) -> ComposeResult:
        yield Static(
            "Queue: decision=unreviewed | job family=all | title/company=all",
            id="filters",
        )
        with Horizontal(id="workspace"):
            yield DataTable(id="queue", cursor_type="row", zebra_stripes=True)
            yield RichLog(id="description", wrap=True, markup=False)
        yield Static(id="counts")
        yield Static("Ready — Space cycles the review decision; Ctrl-Z undoes.", id="undo-status")
        yield Static("Recent: none", id="recent")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#queue", DataTable)
        for label, key, width in (
            ("Title", "title", 24),
            ("Company", "company", 20),
            ("Location", "location", 18),
            ("Date", "date", 11),
            ("Pay", "pay", 14),
            ("Job family", "family", 26),
            ("Decision", "decision", 16),
            ("Status", "status", 13),
        ):
            table.add_column(label, key=key, width=width)
        self._reload_queue()

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

    def _display_row(self, row: dict[str, Any]) -> tuple[str, ...]:
        return (
            row.get("title") or "",
            row.get("company") or "",
            row.get("location") or "",
            (row.get("date_posted") or "")[:10],
            jobsview._pay_label(row),
            jobsview._family_label(row),
            self._decision(row),
            self._status(row),
        )

    def _reload_queue(self, selected_url: str | None = None) -> None:
        self._rows = self._read_rows()
        self._rows_by_url = {row["job_url"]: row for row in self._rows}
        self._queue = [row for row in self._rows if self._decision(row) == "unreviewed"]
        table = self.query_one("#queue", DataTable)
        table.clear()
        for row in self._queue:
            table.add_row(*self._display_row(row), key=row["job_url"])
        if self._queue:
            selected_index = next(
                (i for i, row in enumerate(self._queue) if row["job_url"] == selected_url),
                0,
            )
            self._place_cursor(table, selected_index)
        else:
            self._show_detail(None)
        self._update_counts()
        self._update_recent()

    def _update_counts(self) -> None:
        kept = sum(self._decision(row) == "keep" for row in self._rows)
        false_positives = sum(self._decision(row) == "false_positive" for row in self._rows)
        self.query_one("#counts", Static).update(
            f"Unreviewed remaining: {len(self._queue)}  |  Kept: {kept}  |  "
            f"False positives: {false_positives}"
        )

    def _update_recent(self) -> None:
        recent = []
        for job_url, decision, status in reversed(self._recent[-3:]):
            row = self._rows_by_url.get(job_url, {})
            title = row.get("title") or job_url
            recent.append(f"{title}: {decision} / {status}")
        text = "Recent: " + ("; ".join(recent) if recent else "none")
        self.query_one("#recent", Static).update(text)

    def _show_detail(self, index: int | None) -> None:
        detail = self.query_one("#description", RichLog)
        detail.clear()
        if index is None or index < 0 or index >= len(self._queue):
            detail.write("No unreviewed rows in the current queue.")
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

    def action_show_detail(self) -> None:
        self.set_focus(self.query_one("#description", RichLog))

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
        """Re-point the three cells a decision or status can change."""
        table = self.query_one("#queue", DataTable)
        table.update_cell(row["job_url"], "decision", self._decision(row))
        table.update_cell(row["job_url"], "status", self._status(row))
        table.update_cell(row["job_url"], "family", jobsview._family_label(row))

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
        leaves_queue = new_decision != "unreviewed"
        if leaves_queue:
            self._queue.remove(row)
            table.remove_row(job_url)
        else:
            self._refresh_row(row)
        self._advance_to(index + (0 if leaves_queue else 1))
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
            self.query_one("#undo-status", Static).update(
                f"Undid {title}: {current_decision}/{current_status} → "
                f"{previous_decision}/{previous_status}"
            )
            self.set_focus(self.query_one("#queue", DataTable))
            return
