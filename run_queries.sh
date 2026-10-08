#!/usr/bin/env bash
# Run every active search term from queries.txt as one CLI invocation.
#
#   ./run_queries.sh                    # all families, 600 results each
#   RESULTS_WANTED=100 ./run_queries.sh  # smaller first run
#   LOCATION="Vancouver, WA" ./run_queries.sh
#
# Each line of queries.txt becomes one --search-term, carrying as --term-label
# the family header (# --- <Family> ---) sitting above it, so every scraped row
# records the job family it came from. The CLI persists results after every
# term, so if one family fails the others are still saved and the script exits
# non-zero.
set -uo pipefail

cd "$(dirname "$0")" || exit

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

# Walk queries.txt once. Each non-blank, non-comment line is one search term,
# and it inherits the label of the nearest preceding "# --- <Family> ---"
# header, keeping --search-term and --term-label paired by position.
TERMS=()
LABELS=()
label=''
while IFS= read -r line || [ -n "$line" ]; do
  # Ignore whitespace at both ends of the line, so an indented header still
  # counts and one ending in a stray space or a carriage return parses instead
  # of falling through as a comment and inheriting the previous family.
  trimmed="${line#"${line%%[![:space:]]*}"}"
  trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
  case "$trimmed" in
    '# --- '*' ---')
      label="${trimmed#'# --- '}"
      label="${label%' ---'}"
      ;;
    '#'* | '') ;;
    *)
      TERMS+=("$line")
      LABELS+=("$label")
      ;;
  esac
done < "$QUERIES_FILE"

if [ ${#TERMS[@]} -eq 0 ]; then
  echo "No active search terms in $QUERIES_FILE" >&2
  exit 1
fi

EST=$(((RESULTS_WANTED / BATCH_SIZE) * SLEEP_TIME * ${#TERMS[@]}))
echo "Running ${#TERMS[@]} search term(s), location='${LOCATION}', ${RESULTS_WANTED} results each."
echo "Roughly $((EST / 60)) min minimum, plus sleep between terms. Output -> ${OUTPUT_DIR}/"
echo

ARGS=()
for i in "${!TERMS[@]}"; do
  ARGS+=(--search-term "${TERMS[$i]}" --term-label "${LABELS[$i]}")
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

