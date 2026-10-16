Status: resolved
Type: task

# 09 — Confirm the first screen renders on a real terminal

Agent sessions in this repo have been `TERM=dumb`, so rendering cannot be confirmed from
one. The bench is a UI; a screen that renders in a headless pilot but not on your terminal
is a broken screen. About five minutes, once, before ticket 06 starts.

## Human steps

1. `make bench-setup` (Textual into `.venv`).
2. `.venv/bin/python jobsview.py review`.
3. Confirm: the app starts, the table is populated, the detail pane renders a description
   as markdown, the footer shows the counts, and colours show at all.
4. Resize the terminal to something small, then back. Confirm the panes do not collapse
   into an unreadable line.
5. Answer: does it look right, and is the default flat queue the right opening view?

## Acceptance

- A one-line note appended to this file under `## Comments` recording the date, the
  terminal used, and whether the render is acceptable.
- If anything is wrong, describe it in the same comment block; the implementer fixes it
  before 06 begins.

## Blocked by

[05](05-bench-tui.md)

## Comments

2026-10-08 — `xterm-256color` pty, 140×40 → 62×28 → 140×40: acceptable by the screen checks after fixing column reflow, narrow-width horizontal scrolling, and footer overflow; the 302-row queue, markdown detail, counts, truecolor, and Undo/Quit were observed. All eight columns remain in the layout at 140+ columns; below that, left/right scroll the minimum-width table. The flat unreviewed queue remains the right opening view per the spec. Human visual confirmation on the target terminal is still welcome.

2026-10-08 follow-up — User confirmed the screen looks good visually. Enter now toggles keyboard focus between the job list and the always-visible detail pane, with a focus border; Ctrl+J/K scrolls the detail while preserving list focus. Verified with the headless pilot and an isolated xterm-256color pty. Ticket resolved.
