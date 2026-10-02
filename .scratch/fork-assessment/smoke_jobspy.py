import pandas as pd
from jobspy import scrape_jobs

df = scrape_jobs(
    site_name="indeed",
    search_term="(retail OR cashier OR \"store associate\")",
    location="Portland, OR",
    distance=10,
    results_wanted=8,
    country_indeed="usa",
    hours_old=24,
)
print("ROWS:", len(df))
print("COLUMNS:", list(df.columns))
if len(df):
    print(df[["title", "company", "location", "date_posted"]].head(8).to_string())
    print("SAMPLE URL:", df.iloc[0].get("job_url"))