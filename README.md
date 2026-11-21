# GraphOne Pipeline (Demo Task)

Async ingestion pipeline for AI-ecosystem data: research papers, startups, products, jobs and news, with a multi-tier LLM extraction layer and deterministic entity resolution.

## Setup

1. python -m venv venv
2. venv\Scripts\activate
3. pip install -r requirements.txt
4. Copy .env.example to .env and fill in your keys

Keys in .env: GITHUB_TOKEN, GEMINI_API_KEY, GROQ_API_KEY, optional DEEPSEEK_API_KEY, GEMINI_MODEL, GROQ_MODEL.

## Run

| Step | Command | Output |
|---|---|---|
| Papers + GitHub stars | python -m src.crawler.papers | data/papers.json |
| Startups | python -m src.crawler.startups | data/startups.json |
| Products | python -m src.crawler.products | data/products.json |
| Jobs + news (24h) | python -m src.crawler.signals | data/jobs.json, data/news.json |
| LLM extraction demo | python -m src.llm.orchestrator | prints validated JSON |
| Entity resolution | python -m src.resolver.resolver | data/entity_mapping_log.json |
| CSV export for Sheets | python -m src.export_csv | data/export/*.csv |

## Architecture

- **crawler/**: asyncio + aiohttp, semaphore-bounded concurrency, exponential backoff with jitter, GitHub rate-limit header handling, slow retry for arXiv.
- **llm/orchestrator.py**: Gemini -> Groq -> DeepSeek fallback. Token-budget truncation keeps the most information-dense paragraphs. On 413 the budget is halved and retried. 429 and 5xx use backoff with jitter. A validator nulls any extracted value that does not literally appear in the source text.
- **resolver/**: normalisation (case, punctuation, legal suffixes), exact alias match, then RapidFuzz match at score 92 or higher for names of 5+ characters. Every decision is logged.
- **Freshness**: every job and news item needs a source timestamp and is kept only if from the last 24 hours. Relative dates go through dateparser. data/seen.json stores URL hashes so reruns never reprocess an article.

## Data sources and honesty notes

- **Papers**: arXiv API. The GitHub URL comes from regex on the abstract or comment, and stars come from the GitHub API (null when the repo is missing). No LLM is involved, so there is no hallucination risk.
- **Startups**: Y Combinator directory via the community mirror yc-oss.github.io. employeeCount is null when absent.
- **Products**: Hugging Face Spaces API. pricingModel is null because the source does not state it, and it is never guessed. startupName is the Space owner, which may be an individual.
- **Jobs**: We Work Remotely, Arbeitnow, Jobicy, RemoteOK, Remotive. RemoteOK and Remotive are monitored but returned 0 items in the last 24h at run time. role_family is filled only when the source gives a category.
- **News**: TechCrunch AI, VentureBeat AI, MIT Technology Review AI, The Verge AI, Hugging Face Blog (RSS).
- The entity resolution seed list has about 50 mocked startups, so most names remain unmatched.

## Anti-bot strategy (Phase V)

See architecture.pdf. Summary: prefer APIs and RSS, honour robots.txt and per-domain rate limits, and for JavaScript-heavy or Cloudflare/Datadome sites use async Playwright with persistent sessions, realistic headers, residential proxy rotation and human-like pacing. Never brute-force captchas.