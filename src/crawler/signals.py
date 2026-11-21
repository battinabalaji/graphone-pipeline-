import asyncio, hashlib, json, logging, os
from datetime import datetime, timedelta, timezone

import aiohttp, dateparser, feedparser, trafilatura

from src.crawler.papers import get
from src.schemas import JobRecord, NewsRecord

log = logging.getLogger("signals")
NOW = datetime.now(timezone.utc)
WINDOW = timedelta(hours=24)
SETTINGS = {"RETURN_AS_TIMEZONE_AWARE": True, "TIMEZONE": "UTC", "TO_TIMEZONE": "UTC"}
HDR = {"User-Agent": "Mozilla/5.0 (graphone-trial/1.0)"}

NEWS_FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "MIT Technology Review AI": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
}


def to_dt(v):
    """Normalize epoch numbers, ISO strings and relative dates ('2 hours ago') to UTC."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        return datetime.fromtimestamp(int(v), tz=timezone.utc)
    return dateparser.parse(str(v), settings=SETTINGS)


def fresh(dt):
    return dt is not None and NOW - WINDOW <= dt <= NOW + timedelta(minutes=5)


def h(url):
    return hashlib.sha1(url.encode()).hexdigest()


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


# ---------------- JOBS ----------------
def job(source, url, company, title, dt, remote, family):
    if not (url and company and fresh(dt)):
        return None
    try:
        return JobRecord(source={"name": source, "url": url},
                         content={"title": title, "company": company.strip(), "date": dt,
                                  "is_remote": remote, "role_family": family})
    except Exception as e:
        log.error("invalid job %s: %s", url, e)


async def jobs_remoteok(s):
    d = await get(s, "https://remoteok.com/api", HDR, True)
    for j in (d if isinstance(d, list) else [])[1:]:  # first item is a legal notice
        yield job("RemoteOK", j.get("url"), j.get("company"), j.get("position"),
                  to_dt(j.get("epoch") or j.get("date")), True, None)


async def jobs_remotive(s):
    d = await get(s, "https://remotive.com/api/remote-jobs", HDR, True)
    for j in (d or {}).get("jobs", []) if isinstance(d, dict) else []:
        yield job("Remotive", j.get("url"), j.get("company_name"), j.get("title"),
                  to_dt(j.get("publication_date")), True, j.get("category"))


async def jobs_wwr(s):
    xml = await get(s, "https://weworkremotely.com/remote-jobs.rss", HDR)
    for e in feedparser.parse(xml).entries if xml else []:
        company, _, title = e.title.partition(":")
        yield job("We Work Remotely", e.link, company, title.strip() or None,
                  to_dt(e.get("published")), True, None)


async def jobs_arbeitnow(s):
    d = await get(s, "https://www.arbeitnow.com/api/job-board-api", HDR, True)
    for j in (d or {}).get("data", []) if isinstance(d, dict) else []:
        yield job("Arbeitnow", j.get("url"), j.get("company_name"), j.get("title"),
                  to_dt(j.get("created_at")), j.get("remote"), None)


async def jobs_jobicy(s):
    d = await get(s, "https://jobicy.com/api/v2/remote-jobs?count=100", HDR, True)
    for j in (d or {}).get("jobs", []) if isinstance(d, dict) else []:
        ind = j.get("jobIndustry")
        yield job("Jobicy", j.get("url"), j.get("companyName"), j.get("jobTitle"),
                  to_dt(j.get("pubDate")), True, ind[0] if isinstance(ind, list) and ind else None)


async def collect_jobs(s):
    out = []
    for fn in (jobs_remoteok, jobs_remotive, jobs_wwr, jobs_arbeitnow, jobs_jobicy):
        try:
            got = [r async for r in fn(s) if r]
            log.info("%s: %s fresh jobs", fn.__name__, len(got))
            out += got
        except Exception as e:
            log.error("%s failed: %r", fn.__name__, e)
    return out


# ---------------- NEWS ----------------
async def full_text(s, url, sem):
    async with sem:
        html = await get(s, url, HDR)
    if not html or html in ("UNAUTH", "RATELIMIT"):
        return None
    return await asyncio.to_thread(trafilatura.extract, html)


async def collect_news(s, seen):
    sem, out = asyncio.Semaphore(5), []
    for name, feed in NEWS_FEEDS.items():
        xml = await get(s, feed, HDR)
        if not xml or xml in ("UNAUTH", "RATELIMIT"):
            log.error("feed failed: %s", name)
            continue
        cands = []
        for e in feedparser.parse(xml).entries:
            dt = to_dt(e.get("published") or e.get("updated"))
            if fresh(dt) and e.get("link") and h(e.link) not in seen:
                cands.append((e, dt))
        texts = await asyncio.gather(*(full_text(s, e.link, sem) for e, _ in cands))
        for (e, dt), text in zip(cands, texts):
            try:
                out.append(NewsRecord(source={"name": name, "url": e.link},
                                      content={"title": " ".join(e.title.split()),
                                               "published_date": dt, "full_text": text}))
                seen[h(e.link)] = NOW.isoformat()
            except Exception as ex:
                log.error("invalid news %s: %s", e.get("link"), ex)
        log.info("%s: %s new fresh articles", name, len(cands))
    return out


def merge(path, new):
    """Keep earlier records still inside the 24h window; add new ones, de-duplicated by URL."""
    old = load(path, [])
    by_url = {r["source"]["url"]: r for r in old}
    for r in new:
        by_url[str(r.source.url)] = r.model_dump(mode="json")
    key = "published_date" if "published_date" in next(iter(by_url.values()), {"content": {}})["content"] else "date"
    keep = [r for r in by_url.values() if fresh(to_dt(r["content"][key]))]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False)
    return len(keep)


async def main():
    seen = load("data/seen.json", {})
    async with aiohttp.ClientSession() as s:
        jobs = await collect_jobs(s)
        news = await collect_news(s, seen)
    os.makedirs("data", exist_ok=True)
    nj = merge("data/jobs.json", jobs)
    nn = merge("data/news.json", news)
    with open("data/seen.json", "w", encoding="utf-8") as f:
        json.dump(seen, f)
    log.info("jobs.json: %s records, news.json: %s records (all within 24h)", nj, nn)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())