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

## Setup

### Requirements

- Git
- Docker Desktop
- Docker Compose
- Python 3.12+ for local development
- OpenRouter API key

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/signalpost.git
cd signalpost

### 2. Configure environment

```bash
cp .env.example .env
Add your OpenRouter API key to .env.

### 3. Run
```bash
./run.sh