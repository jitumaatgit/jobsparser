from jobspy import scrape_jobs

TERMS = '"retail" OR cashier OR merchandiser'
all_rows = []
for offset in (0, 25, 50):
    df = scrape_jobs(site_name="indeed", search_term=TERMS, location="Portland, OR",
                     distance=10, results_wanted=25, offset=offset,
                     country_indeed="usa", hours_old=24)
    if len(df):
        all_rows.extend(df["job_url"].tolist())

print("raw rows fetched:", len(all_rows))
print("unique after dedupe:", len(set(all_rows)))
print("duplicates:", len(all_rows) - len(set(all_rows)))