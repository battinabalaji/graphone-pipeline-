
import asyncio, json, logging, os

import aiohttp

from src.schemas import ProductRecord

log = logging.getLogger("products")
START = "https://huggingface.co/api/spaces?limit=500&sort=likes&direction=-1"
TARGET = 1500


async def main():
    out, seen, url = [], set(), START
    async with aiohttp.ClientSession(headers={"User-Agent": "graphone-trial/1.0"}) as s:
        while url and len(out) < TARGET:
            for attempt in range(5):
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                    if r.status == 200:
                        items = await r.json()
                        url = r.links.get("next", {}).get("url")
                        url = str(url) if url else None
                        break
                    log.warning("HTTP %s, retrying", r.status)
                await asyncio.sleep(2 ** attempt)
            else:
                break
            for it in items:
                sid = it.get("id", "")
                if "/" not in sid or sid in seen:
                    continue
                seen.add(sid)
                owner, name = sid.split("/", 1)
                try:
                    out.append(ProductRecord(
                        source={"name": "Hugging Face Spaces",
                                "url": f"https://huggingface.co/spaces/{sid}"},
                        content={"productName": name, "startupName": owner,
                                 "pricingModel": None},  # not stated by source
                    ))
                except Exception as e:
                    log.error("invalid %s: %s", sid, e)
            log.info("collected %s products", len(out))
            await asyncio.sleep(1)
    os.makedirs("data", exist_ok=True)
    with open("data/products.json", "w", encoding="utf-8") as f:
        json.dump([r.model_dump(mode="json") for r in out], f, ensure_ascii=False)
    log.info("saved %s products", len(out))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())