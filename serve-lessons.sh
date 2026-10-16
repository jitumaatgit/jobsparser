#!/usr/bin/env bash
# Serve this teaching workspace over local HTTP.
#
# Why: lesson HTML links its styling/quiz from ./assets/ via relative paths.
# Sandboxed browsers (e.g. Flatpak Zen) open a local .html through the
# xdg-desktop-portal document portal, which exports ONLY the one file — so the
# sibling ../assets/* can't be read and the page renders unstyled. Serving over
# http:// makes the relative paths resolve as normal web requests, so any
# browser (Zen included) renders it correctly.
#
# Usage:
#   bash serve-lessons.sh [port]        # default port 8777
# then open the printed lesson URL in your browser.
# Stop with Ctrl-C.

set -euo pipefail

PORT="${1:-8777}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Serving $DIR"
echo "on http://127.0.0.1:$PORT/"
echo
echo "Lesson 1   : http://127.0.0.1:$PORT/lessons/0001-connect-and-browse-jobs-db.html"
echo "Cheat sheet: http://127.0.0.1:$PORT/reference/0001-dadbod-dbui-cheatsheet.html"
echo
echo "Stop with Ctrl-C."

exec python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$DIR"
