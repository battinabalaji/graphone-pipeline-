import asyncio, json, logging, os, random, re
from datetime import datetime, timezone
from urllib.parse import quote

import aiohttp, feedparser
from dotenv import load_dotenv

from src.schemas import ResearchPaperRecord

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("papers")

TARGET = 1100
PAGE = 200
ARXIV = "https://export.arxiv.org/api/query"
QUERY = ('(abs:"github.com") AND (cat:cs.LG OR cat:cs.CV OR cat:cs.CL OR cat:cs.AI) '
         'AND submittedDate:[202506010000 TO 202509010000]')
GH_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
TOKEN = (os.getenv("GITHUB_TOKEN") or "").strip() or None
sem = asyncio.Semaphore(10)


async def get(session, url, headers=None, as_json=False, tries=5):
    """GET with exponential backoff + jitter; respects GitHub rate-limit headers."""
    for i in range(tries):
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status == 200:
                    return await (r.json() if as_json else r.text())
                if r.status in (404, 451):
                    return None
                if r.status == 401:
                    return "UNAUTH"
                if r.status in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
                    reset = int(r.headers.get("x-ratelimit-reset", "0"))
                    wait = reset - int(datetime.now(timezone.utc).timestamp())
                    if wait > 120:
                        log.error("GitHub rate limit exhausted, resets in %ss", wait)
                        return "RATELIMIT"
                    await asyncio.sleep(max(wait, 1) + random.random())
                    continue
                log.warning("HTTP %s on %s", r.status, url[:90])
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("net error %r on %s", e, url[:90])
        await asyncio.sleep(min(60, 2 ** i) + random.random())
    return None


async def get_arxiv(session, url, tries=6):
    """arXiv needs long waits after a 429."""
    for i in range(tries):
        text = await get(session, url, tries=1)
        if text and text not in ("UNAUTH", "RATELIMIT"):
            return text
        wait = 30 * (i + 1) + random.random() * 5
        log.warning("arXiv not ready, waiting %.0fs (attempt %s/%s)", wait, i + 1, tries)
        await asyncio.sleep(wait)
    return None


def find_repo(text):
    m = GH_RE.search(text or "")
    if not m:
        return None
    owner, repo = m.group(1), m.group(2).rstrip(".,;:)")
    repo = repo[:-4] if repo.endswith(".git") else repo
    return f"{owner}/{repo}"


async def fetch_stars(session, repo):
    global TOKEN
    async with sem:
        h = {"Accept": "application/vnd.github+json"}
        if TOKEN:
            h["Authorization"] = f"Bearer {TOKEN}"
        data = await get(session, f"https://api.github.com/repos/{repo}", h, True)
        if data == "UNAUTH":
            log.warning("GitHub token rejected, continuing without it")
            TOKEN = None
            data = await get(session, f"https://api.github.com/repos/{repo}",
                             {"Accept": "application/vnd.github+json"}, True)
        if isinstance(data, dict):
            return data.get("stargazers_count")
        return None


async def build_record(session, e):
    repo = find_repo(e.get("summary", "") + " " + e.get("arxiv_comment", ""))
    stars = await fetch_stars(session, repo) if repo else None
    if repo and stars is None:
        log.info("no stars for %s", repo)
    try:
        return ResearchPaperRecord(
            source={"name": "arXiv", "url": e.id},
            content={
                "title": " ".join(e.title.split()),
                "authors": [a.name for a in e.get("authors", [])],
                "paper_url": e.id,
                "github_url": f"https://github.com/{repo}" if repo else None,
                "github_stars": stars,
                "published_date": e.published,
                "github_stars_fetched_at": datetime.now(timezone.utc) if stars is not None else None,
            },
        )
    except Exception as ex:
        log.error("validation failed for %s: %s", e.id, ex)
        return None


def save(out):
    os.makedirs("data", exist_ok=True)
    with open("data/papers.json", "w", encoding="utf-8") as f:
        json.dump([r.model_dump(mode="json") for r in out], f, ensure_ascii=False)


async def main():
    out, seen = [], set()
    async with aiohttp.ClientSession(headers={"User-Agent": "graphone-trial/1.0"}) as session:
        start = 0
        while len(out) < TARGET:
            url = (f"{ARXIV}?search_query={quote(QUERY)}&start={start}"
                   f"&max_results={PAGE}&sortBy=submittedDate&sortOrder=descending")
            xml = await get_arxiv(session, url)
            entries = feedparser.parse(xml).entries if xml else []
            if not entries:
                log.info("no more entries at start=%s", start)
                break
            entries = [e for e in entries if e.id not in seen]
            seen.update(e.id for e in entries)
            recs = await asyncio.gather(*(build_record(session, e) for e in entries))
            out += [r for r in recs if r]
            log.info("collected %s papers", len(out))
            save(out)
            start += PAGE
            await asyncio.sleep(6)
    save(out)
    with_stars = sum(1 for r in out if r.content.github_stars is not None)
    log.info("saved %s papers (%s with GitHub stars)", len(out), with_stars)


if __name__ == "__main__":
    asyncio.run(main())