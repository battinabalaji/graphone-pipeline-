import json, logging, os, re

from rapidfuzz import fuzz, process

log = logging.getLogger("resolver")
SUFFIX = re.compile(r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|gmbh|pbc|lp|plc)\b\.?", re.I)
THRESHOLD = 92


def clean(s):
    s = SUFFIX.sub(" ", str(s).lower().replace("&", " and "))
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def compact(s):
    return clean(s).replace(" ", "")


class Resolver:
    def __init__(self, path="data/seed_startups.json"):
        self.seed = json.load(open(path, encoding="utf-8"))
        self.exact = {}
        for e in self.seed:
            for name in [e["canonical"], *e["aliases"]]:
                self.exact[compact(name)] = e["canonical"]
        self.keys = list(self.exact)
        self.log = []

    def resolve(self, raw, source="unknown"):
        key = compact(raw)
        canonical, method, score = None, "unmatched", 0
        if key in self.exact:
            canonical, method, score = self.exact[key], "exact", 100
        elif len(key) >= 5:  # fuzzy only on longer names, to avoid false merges
            hit = process.extractOne(key, self.keys, scorer=fuzz.ratio, score_cutoff=THRESHOLD)
            if hit:
                canonical, method, score = self.exact[hit[0]], "fuzzy", round(hit[1], 1)
        self.log.append({"raw_name": raw, "canonical_name": canonical or raw.strip(),
                         "method": method, "score": score, "source": source})
        return canonical or raw.strip()


def load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        return []


def main():
    r = Resolver()
    for t in ["OpenAI, Inc.", "Open AI", "openai", "Anthropic PBC", "Mistral", "Hugging-Face",
              "Eleven Labs", "Weights and Biases", "Stabilty AI", "Cohere Inc."]:
        r.resolve(t, "test")
    for rec in load("data/startups.json"):
        r.resolve(rec["content"]["entityName"], "startups")
    for rec in load("data/products.json"):
        r.resolve(rec["content"]["startupName"], "products")
    for rec in load("data/jobs.json"):
        r.resolve(rec["content"]["company"], "jobs")
    os.makedirs("data", exist_ok=True)
    json.dump(r.log, open("data/entity_mapping_log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    by = {}
    for row in r.log:
        by[row["method"]] = by.get(row["method"], 0) + 1
    print("rows:", len(r.log), by)
    for row in r.log[:10]:
        print(row["raw_name"], "->", row["canonical_name"], row["method"], row["score"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()