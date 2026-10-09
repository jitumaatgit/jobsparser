RESULTS_WANTED ?= 600
BATCH_SIZE ?= 100
SLEEP_TIME ?= 60
HOURS_OLD ?= 24
INDEED_COUNTRY ?= US
DISTANCE ?= 10
OUTPUT_DIR ?= data

# Local-only tooling. This fork is not published to PyPI; it runs from source.
.PHONY: setup scrape index viewer-setup bench-setup view clean
setup:
	python3 -m venv .venv
	.venv/bin/pip install -e ./jobsparser

scrape:
	@if [ -z "$(SEARCH_TERM)" ]; then echo "Usage: make scrape SEARCH_TERM='...' LOCATION='...'"; exit 1; fi
	@if [ -z "$(LOCATION)" ]; then echo "Usage: make scrape SEARCH_TERM='...' LOCATION='...'"; exit 1; fi
	.venv/bin/jobsparser \
		--search-term '$(SEARCH_TERM)' \
		--location "$(LOCATION)" \
		--results-wanted $(RESULTS_WANTED) \
		--batch-size $(BATCH_SIZE) \
		--sleep-time $(SLEEP_TIME) \
		--hours-old $(HOURS_OLD) \
		--indeed-country $(INDEED_COUNTRY) \
		--distance $(DISTANCE) \
		--output-dir $(OUTPUT_DIR)

index:
	python3 jobsview.py ingest

viewer-setup:
	.venv/bin/pip install 'datasette>=0.65.2,<1'

bench-setup:
	.venv/bin/pip install 'textual>=8.2.8'

view: index
	@test -x .venv/bin/datasette || { echo "Datasette not installed. Run: make viewer-setup" >&2; exit 1; }
	.venv/bin/datasette serve data/jobs.db --host 127.0.0.1 --port 8001

clean:
	rm -rf build dist *.egg-info jobsparser/src/*.egg-info
	find . -name __pycache__ -type d -not -path "./.venv/*" -exec rm -rf {} +