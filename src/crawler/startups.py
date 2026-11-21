import asyncio, json, logging, os

import aiohttp

from src.crawler.papers import get
from src.schemas import StartupRecord

log = logging.getLogger("startups")
# Community-maintained mirror of the public YC company directory
URL = "https://yc-oss.github.io/api/companies/all.json"
TARGET = 1500


async def main():
    async with aiohttp.ClientSession(headers={"User-Agent": "graphone-trial/1.0"}) as s:
        data = await get(s, URL, as_json=True)
    if not isinstance(data, list):
        log.error("could not fetch YC list: %r", data)
        return
    out, seen = [], set()
    for c in data:
        name, slug = (c.get("name") or "").strip(), c.get("slug")
        url = c.get("url") or c.get("website")
        if not name or not url or slug in seen:
            continue
        seen.add(slug)
        size = c.get("team_size")
        try:
            out.append(StartupRecord(
                source={"name": "Y Combinator", "url": url},
                content={"entityName": name,
                         "data": {"employeeCount": size if isinstance(size, int) else None}},
            ))
        except Exception as e:
            log.error("invalid %s: %s", name, e)
        if len(out) >= TARGET:
            break
    os.makedirs("data", exist_ok=True)
    with open("data/startups.json", "w", encoding="utf-8") as f:
        json.dump([r.model_dump(mode="json") for r in out], f, ensure_ascii=False)
    log.info("saved %s startups", len(out))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())