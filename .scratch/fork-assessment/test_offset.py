from jobspy import scrape_jobs

def grab(offset, n):
    df = scrape_jobs(
        site_name="indeed", search_term='"retail" OR cashier',
        location="Portland, OR", distance=10, results_wanted=n,
        offset=offset, country_indeed="usa", hours_old=24,
    )
    return set(df["job_url"]) if len(df) else set()

a = grab(0, 5)
b = grab(5, 5)
c = grab(10, 5)
print("offset0 :", len(a))
print("offset5 :", len(b))
print("offset10:", len(c))
print("0 vs5 overlap :", len(a & b))
print("5 vs10 overlap:", len(b & c))
print("0 vs10 overlap:", len(a & c))
print("total distinct across 3 batches:", len(a | b | c))
print("requested total:", 15)