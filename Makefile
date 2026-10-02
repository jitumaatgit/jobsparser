RESULTS_WANTED ?= 600
BATCH_SIZE ?= 100
SLEEP_TIME ?= 60
HOURS_OLD ?= 24
INDEED_COUNTRY ?= US
DISTANCE ?= 10
OUTPUT_DIR ?= data

# Local-only tooling. This fork is not published to PyPI; it runs from source.
.PHONY: setup scrape clean
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

clean:
	rm -rf build dist *.egg-info jobsparser/src/*.egg-info
	find . -name __pycache__ -type d -not -path "./.venv/*" -exec rm -rf {} +