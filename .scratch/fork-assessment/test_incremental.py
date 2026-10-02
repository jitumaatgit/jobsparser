"""Verify the incremental CSV write: partial results must survive a later failure."""
import sys, os, glob, csv, shutil
sys.argv = ["jobsparser"]
from click.testing import CliRunner
from jobsparser.cli import main
import jobsparser.cli as clim

OUT = ".scratch/fork-assessment/incr"
shutil.rmtree(OUT, ignore_errors=True)

calls = {"n": 0}
real = clim.scrape_jobs
def flaky(**kw):
    calls["n"] += 1
    if calls["n"] >= 3:          # 3rd search term's batches all fail
        raise RuntimeError("simulated network failure on 3rd term")
    return real(**kw)
clim.scrape_jobs = flaky

runner = CliRunner()
result = runner.invoke(main, [
    "--search-term", '"retail" OR cashier',
    "--search-term", '"data entry"',
    "--search-term", '"software engineer"',
    "--location", "Portland, OR", "--distance", "10",
    "--results-wanted", "4", "--batch-size", "4", "--sleep-time", "1",
    "--hours-old", "24", "--indeed-country", "US", "--output-dir", OUT,
    "--max-retries", "2",
])
clim.scrape_jobs = real

print("exit code:", result.exit_code)
files = glob.glob(f"{OUT}/*.csv")
print("csv files written:", len(files))
rows = list(csv.DictReader(open(files[0]))) if files else []
urls = [r["job_url"] for r in rows]
print("rows surviving the crash:", len(rows))
print("duplicate urls:", len(urls) - len(set(urls)))
print("has title/company columns:", all(c in rows[0] for c in ("title","company","job_url")) if rows else False)
print("sample titles:", [r["title"] for r in rows[:4]])