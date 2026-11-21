import asyncio, json, logging

import aiohttp

from src.llm.orchestrator import extract
from src.resolver.resolver import Resolver

log = logging.getLogger("enrich")
INSTR = ('Return JSON with keys: "companyName" (the main company the article is about, exactly as '
         'written in the text, or null), "employeeCount" (integer, only if stated, else null), '
         '"pricingModel" (FREE, FREEMIUM, PAID or ENTERPRISE, only if stated, else null).')


async def main():
    news = json.load(open("data/news.json", encoding="utf-8"))
    resolver, out = Resolver(), []
    sem = asyncio.Semaphore(2)

    async with aiohttp.ClientSession() as s:
        async def one(item):
            text = item["content"].get("full_text")
            if not text:
                return
            async with sem:
                res = await extract(s, INSTR, text)
            if res is None:
                return
            name = res.get("companyName")
            out.append({
                "source_url": item["source"]["url"],
                "title": item["content"]["title"],
                "extracted": res,
                "canonical_company": resolver.resolve(name, "news-llm") if name else None,
            })

        await asyncio.gather(*(one(i) for i in news))

    with open("data/news_enriched.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"enriched {len(out)} of {len(news)} articles")
    for r in out[:5]:
        print(r["canonical_company"], "|", r["source_url"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())