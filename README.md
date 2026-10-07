# SIGNALPOST

Signalpost researches Norwegian companies from a 9-digit organization number and produces evidence-backed, validated company facts with source links, observation dates, conflict protection, and change history.

## Challenge-aligned pipeline

`Org.nr → Identity → Sources → Evidence → Extraction → Validation → Conflict Detection → Facts → Change Detection → Updated Company Profile`

## Complete phases

1. **Company Lookup** — validate Norwegian org.nr with checksum; fetch and identify the exact company from Brønnøysundregistrene.
2. **Database** — PostgreSQL + SQLAlchemy + Alembic; companies, sources, facts, history, and research-run logs.
3. **Source & Evidence Collection** — Brreg, official website, and free DuckDuckGo discovery; SSRF protection, canonical URLs, URL/content hashes, deduplication, and source identity verification. Search results are candidates only.
4. **Fact Extraction** — OpenRouter/OpenAI-compatible LLM plus deterministic fallback for employees, industry, address, revenue, profit, founded year, phone, email, website, legal form, CEO/chair where supported.
5. **Fact Validation** — schema/type/range/format validation, evidence grounding, company/source verification, and unresolved-conflict rejection.
6. **Change Detection** — snapshot the previous verified state before new observations; detect added/changed/removed facts and persist history.
7. **Performance & Reliability** — async HTTP, bounded concurrency, retries, timeouts, TTL caching, URL deduplication, and 2,000-request/45-minute/$10 budgets.
8. **1,000+ Profiles** — batch CSV/text processing, concurrency, retries, failure tracking, and profile completeness tracking.
9. **Evaluation** — random sample evaluation with coverage, identity/evidence, update, explanation, and usability signals; target ≥65/100 and ≥21/35 coverage.
10. **Production & Submission** — Docker, PostgreSQL, FastAPI, CLI, migrations, tests, one-command startup, model/API configuration, and cost reporting.

## Configuration

Copy `.env.example` to `.env`. The default setup uses your OpenRouter key and free DuckDuckGo discovery:

```env
OPENROUTER_API_KEY=your_key
LLM_PROVIDER=openrouter
LLM_MODEL=openai/gpt-4o-mini
SEARCH_PROVIDER=duckduckgo
MAX_REQUESTS=2000
MAX_RUNTIME_SECONDS=2700
MAX_COST_USD=10
HTTP_TIMEOUT=15
HTTP_CONCURRENCY=12
HTTP_CACHE_TTL_SECONDS=300
```

## One command with Docker

```bash
docker compose up --build
```

The API is available at `http://127.0.0.1:8000`. Docker runs Alembic migrations before starting FastAPI.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn signalpost.api:app --reload
```

## API

### Research

```bash
curl -s -X POST http://127.0.0.1:8000/research \
  -H 'Content-Type: application/json' \
  -d '{"company_number":"923609016"}'
```

### Current profile

`GET /companies/{orgnr}`

### Sources

`GET /companies/{orgnr}/sources`

### Change history

`GET /companies/{orgnr}/history`

### Bulk

`POST /bulk-research` with `{"company_numbers":[...]}`

### Evaluation

`POST /evaluate?sample_size=100`

### Health

`GET /health`

## CLI

```bash
python -m signalpost.cli research 923609016
python -m signalpost.cli bulk companies.csv --concurrency 4
python -m signalpost.cli evaluate --n 100
```

## Safety and correctness

DuckDuckGo is used only to discover candidate URLs. A search result is never trusted as a fact. Every fetched source passes SSRF protection and company-identity verification. Every published fact must have grounded evidence from a verified source. If conflicting values cannot be deterministically resolved, they are not published.

## Submission checklist

- [ ] ≥1,000 complete company profiles
- [ ] Repository URL
- [ ] Exact commit hash
- [ ] One-command run
- [ ] Model/API details
- [ ] Expected run cost
- [ ] Tests passing in the target environment
