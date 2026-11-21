

import asyncio, json, logging, os, random, re

import aiohttp
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("llm")


class RateLimited(Exception):
    def __init__(self, retry_after=None):
        self.retry_after = retry_after


class TooLarge(Exception):
    pass


class ProviderError(Exception):
    pass


# Model names are overridable from .env because providers rename models often.
PROVIDERS = [
    {"name": "gemini", "key": "GEMINI_API_KEY", "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
     "budget": 24000},
    {"name": "groq", "key": "GROQ_API_KEY", "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
     "budget": 5000},
    {"name": "deepseek", "key": "DEEPSEEK_API_KEY", "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
     "budget": 20000},
]

SYSTEM = ("You extract structured data from text. Use ONLY information explicitly stated in the text. "
          "If a field is not stated, return null. Never guess or infer. Reply with a single JSON object only.")


# ---------- chunking / truncation ----------
def est_tokens(s):
    return len(s) // 4 + 1


def smart_truncate(text, max_tokens):
    """Keep the most information-dense paragraphs, preserving original order.
    Always keeps the opening paragraph."""
    if est_tokens(text) <= max_tokens:
        return text
    paras = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    if not paras:
        return text[: max_tokens * 4]

    def score(p):
        digits = sum(c.isdigit() for c in p)
        caps = len(re.findall(r"\b[A-Z][a-z]+", p))
        return digits * 2 + caps + min(len(p), 400) / 40

    keep, used = {0}, est_tokens(paras[0])
    for i in sorted(range(1, len(paras)), key=lambda i: -score(paras[i])):
        t = est_tokens(paras[i])
        if used + t <= max_tokens:
            keep.add(i)
            used += t
    out = "\n".join(paras[i] for i in sorted(keep))
    return out[: max_tokens * 4]


# ---------- provider calls ----------
async def call(session, p, key, prompt):
    timeout = aiohttp.ClientTimeout(total=90)
    if p["name"] == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{p['model']}:generateContent"
        body = {"systemInstruction": {"parts": [{"text": SYSTEM}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
        headers = {"x-goog-api-key": key}
    else:
        url = ("https://api.groq.com/openai/v1/chat/completions" if p["name"] == "groq"
               else "https://api.deepseek.com/chat/completions")
        body = {"model": p["model"], "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": prompt}]}
        headers = {"Authorization": f"Bearer {key}"}
    async with session.post(url, json=body, headers=headers, timeout=timeout) as r:
        if r.status == 429:
            ra = r.headers.get("retry-after")
            raise RateLimited(float(ra) if ra and ra.replace(".", "").isdigit() else None)
        if r.status == 413:
            raise TooLarge()
        if r.status == 400:
            txt = (await r.text()).lower()
            if "too large" in txt or "context" in txt or "token" in txt:
                raise TooLarge()
            raise ProviderError(f"HTTP 400: {txt[:200]}")
        if r.status in (500, 502, 503, 504):
            raise RateLimited(None)
            
        data = await r.json()
    if p["name"] == "gemini":
        return data["candidates"][0]["content"]["parts"][0]["text"]
    return data["choices"][0]["message"]["content"]


def parse_json(txt):
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    return json.loads(txt)


async def run_provider(session, p, key, instruction, text, tries=4):
    budget = p["budget"]
    for attempt in range(tries):
        prompt = f"{instruction}\n\nTEXT:\n{smart_truncate(text, budget)}"
        try:
            return parse_json(await call(session, p, key, prompt))
        except TooLarge:
            budget //= 2  # 413: shrink the payload and retry
            log.warning("%s: payload too large, budget -> %s tokens", p["name"], budget)
            if budget < 300:
                raise ProviderError("cannot shrink further")
        except RateLimited as e:  # 429: exponential backoff + jitter
            wait = (e.retry_after or min(60, 2 ** attempt * 2)) + random.random() * 2
            log.warning("%s: 429, sleeping %.1fs (attempt %s)", p["name"], wait, attempt + 1)
            await asyncio.sleep(wait)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            log.warning("%s: bad output %r", p["name"], e)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("%s: network error %r", p["name"], e)
            await asyncio.sleep(2 ** attempt + random.random())
    raise ProviderError(f"{p['name']} exhausted retries")


# ---------- anti-hallucination validator ----------
def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(s).lower())).strip()


ENUM_EVIDENCE = {"FREE": ["free"], "FREEMIUM": ["freemium", "free tier", "free plan"],
                 "PAID": ["paid", "per month", "pricing", "subscription"],
                 "ENTERPRISE": ["enterprise"]}


def validate(data, source_text):
    """Null out any value that is not literally supported by the source text."""
    src, src_raw = norm(source_text), source_text.lower()
    clean, dropped = {}, []
    for k, v in data.items():
        ok = True
        if v is None or isinstance(v, bool):
            ok = True
        elif k == "pricingModel":
            ok = any(w in src_raw for w in ENUM_EVIDENCE.get(str(v).upper(), []))
        elif isinstance(v, (int, float)):
            ok = str(int(v)) in src_raw or f"{int(v):,}" in src_raw
        elif isinstance(v, list):
            v = [x for x in v if isinstance(x, str) and norm(x) in src]
        elif isinstance(v, str):
            ok = norm(v) in src
        if ok:
            clean[k] = v
        else:
            clean[k] = None
            dropped.append(k)
    if dropped:
        log.info("validator dropped unsupported fields: %s", dropped)
    return clean


# ---------- public entry point ----------
async def extract(session, instruction, text):
    """Try Gemini -> Groq -> DeepSeek. Returns validated dict, or None if every tier fails."""
    for p in PROVIDERS:
        key = (os.getenv(p["key"]) or "").strip()
        if not key:
            log.info("%s: no key, skipping", p["name"])
            continue
        try:
            raw = await run_provider(session, p, key, instruction, text)
            if isinstance(raw, dict):
                log.info("%s: extraction ok", p["name"])
                return validate(raw, text)
        except ProviderError as e:
            log.warning("falling back from %s: %s", p["name"], e)
    log.error("all providers failed")
    return None


async def demo():
    news = json.load(open("data/news.json", encoding="utf-8"))
    item = next((n for n in news if n["content"].get("full_text")), None)
    if not item:
        print("no news with full_text found; run signals first")
        return
    instr = ('Return JSON with keys: "companyName" (the main company discussed, exactly as written), '
             '"employeeCount" (integer, only if stated), "pricingModel" (FREE, FREEMIUM, PAID or ENTERPRISE, '
             "only if stated). Use null for anything not stated.")
    async with aiohttp.ClientSession() as s:
        res = await extract(s, instr, item["content"]["full_text"])
    print("source:", item["source"]["url"])
    print("result:", res)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(demo())