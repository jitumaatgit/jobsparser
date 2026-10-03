#!/usr/bin/env bash
# Run every active search term from queries.txt as one CLI invocation.
#
#   ./run_queries.sh                    # all families, 600 results each
#   RESULTS_WANTED=100 ./run_queries.sh  # smaller first run
#   LOCATION="Vancouver, WA" ./run_queries.sh
#
# Each line of queries.txt becomes one --search-term. The CLI persists results
# after every term, so if one family fails the others are still saved and the
# script exits non-zero.
set -uo pipefail

cd "$(dirname "$0")"

QUERIES_FILE="${QUERIES_FILE:-queries.txt}"
LOCATION="${LOCATION:-Portland, OR}"
DISTANCE="${DISTANCE:-10}"
RESULTS_WANTED="${RESULTS_WANTED:-600}"
BATCH_SIZE="${BATCH_SIZE:-100}"
SLEEP_TIME="${SLEEP_TIME:-60}"
HOURS_OLD="${HOURS_OLD:-24}"
INDEED_COUNTRY="${INDEED_COUNTRY:-US}"
OUTPUT_DIR="${OUTPUT_DIR:-data}"

if [ ! -x .venv/bin/jobsparser ]; then
    echo "jobsparser not installed. Run: make setup" >&2
    exit 1
fi

# Collect active queries: non-blank, not commented.
mapfile -t QUERIES < <(grep -vE '^\s*(#|$)' "$QUERIES_FILE")

if [ ${#QUERIES[@]} -eq 0 ]; then
    echo "No active search terms in $QUERIES_FILE" >&2
    exit 1
fi

EST=$(( (RESULTS_WANTED / BATCH_SIZE) * SLEEP_TIME * ${#QUERIES[@]} ))
echo "Running ${#QUERIES[@]} search term(s), location='${LOCATION}', ${RESULTS_WANTED} results each."
echo "Roughly $((EST / 60)) min minimum, plus sleep between terms. Output -> ${OUTPUT_DIR}/"
echo

ARGS=()
for q in "${QUERIES[@]}"; do
    ARGS+=(--search-term "$q")
done

exec .venv/bin/jobsparser \
    "${ARGS[@]}" \
    --location "$LOCATION" \
    --distance "$DISTANCE" \
    --site indeed \
    --results-wanted "$RESULTS_WANTED" \
    --batch-size "$BATCH_SIZE" \
    --sleep-time "$SLEEP_TIME" \
    --hours-old "$HOURS_OLD" \
    --indeed-country "$INDEED_COUNTRY" \
    --output-dir "$OUTPUT_DIR"