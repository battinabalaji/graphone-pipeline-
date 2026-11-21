import csv, json, os

from src.resolver.resolver import Resolver

OUT = "data/export"
r = Resolver()


def load(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except FileNotFoundError:
        return []


def write(name, header, rows):
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/{name}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(name, len(rows), "rows")


def base(x):
    return [x["schemaVersion"], x["recordType"], x["source"]["name"], x["source"]["url"], x["collectedAt"]]


B = ["schemaVersion", "recordType", "source.name", "source.url", "collectedAt"]

write("Startups", B + ["content.entityName", "raw_name", "content.data.employeeCount"],
      [base(x) + [r.resolve(x["content"]["entityName"], "startups"), x["content"]["entityName"],
                  x["content"]["data"]["employeeCount"]] for x in load("data/startups.json")])

write("Products", B + ["content.productName", "content.startupName", "raw_startupName", "content.pricingModel"],
      [base(x) + [x["content"]["productName"], r.resolve(x["content"]["startupName"], "products"),
                  x["content"]["startupName"], x["content"]["pricingModel"]] for x in load("data/products.json")])

write("Research Papers", B + ["content.title", "content.authors", "content.paper_url", "content.github_url",
                             "content.github_stars", "content.published_date", "github_stars_fetched_at"],
      [base(x) + [c["title"], "; ".join(c["authors"]), c["paper_url"], c["github_url"], c["github_stars"],
                  c["published_date"], c.get("github_stars_fetched_at")]
       for x in load("data/papers.json") for c in [x["content"]]])

write("Jobs", B + ["content.title", "content.company", "raw_company", "content.date", "content.is_remote",
                  "content.role_family"],
      [base(x) + [c["title"], r.resolve(c["company"], "jobs"), c["company"], c["date"], c["is_remote"],
                  c["role_family"]] for x in load("data/jobs.json") for c in [x["content"]]])

write("News", B + ["content.title", "content.published_date", "content.full_text"],
      [base(x) + [c["title"], c["published_date"], (c.get("full_text") or "")[:40000]]
       for x in load("data/news.json") for c in [x["content"]]])

seen, log = set(), []
for row in r.log:
    k = (row["raw_name"], row["source"])
    if k not in seen:
        seen.add(k)
        log.append([row["raw_name"], row["canonical_name"], row["method"], row["score"], row["source"]])
write("Entity Mapping Log", ["raw_name", "canonical_name", "method", "score", "source"], log)