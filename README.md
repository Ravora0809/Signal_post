# SIGNALPOST

Signalpost researches Norwegian companies from a 9-digit organisation number and produces evidence-backed, validated company facts with source links, dates, conflict protection, and change history.

## Pipeline

`Org.nr → Identity → Sources → Evidence → Extraction → Validation → Conflict Detection → Facts → Change Detection → Updated Company Profile`

## Challenge-aligned phases

1. **Company Lookup** — validate the Norwegian org.nr and fetch the exact company from Brønnøysundregistrene (Brreg).
2. **Database** — PostgreSQL + SQLAlchemy + Alembic.
3. **Source & Evidence Collection** — Brreg entity/roles, Regnskapsregisteret, registered website, and discovery search. Unverified sources are rejected.
4. **Fact Extraction** — deterministic extraction for authoritative registry/accounting data; LLM extraction only for permitted non-authoritative enrichment.
5. **Fact Validation** — type/range/format validation, source identity checks, authority ranking, and fail-closed conflict handling.
6. **Change Detection** — compare new observations against the previous verified state.
7. **Performance & Reliability** — async HTTP, bounded concurrency, retries, timeouts, caching, URL deduplication, and request/time/cost budgets.
8. **1,000+ Profiles** — registry CSV import plus official live enrichment.
9. **Evaluation** — local readiness/proxy evaluation; the challenge's hidden evaluator remains authoritative.
10. **Submission** — FastAPI, CLI, Docker, PostgreSQL, migrations, tests, and reproducible configuration.

## Data-integrity rules

- Financial values are extracted from one selected accounting record. `SELSKAP` (parent-company) is preferred over `KONSERN` (consolidated group); the selected `accounting_statement_type`, accounting period, currency, and values come from the same record.
- Financial evidence snippets are sliced from that exact raw record, not searched globally across all years. Structured Regnskapsregisteret facts are rejected if the exact value is not present in their attached evidence/source.
- If the selected record cannot be located in the raw response or its value cannot be tied to the evidence, financial facts fail closed and are not published.
- Employee facts from Brreg retain `registreringsdatoAntallAnsatteEnhetsregisteret` as `as_of`.
- Company status is deterministic from Brreg lifecycle flags; LLM output cannot override it.
- A source that cannot be tied to the requested company is rejected and cannot produce published facts.
- Equal-authority conflicting values are not published.
- API responses expose both `observed_at` and `as_of` when available.

## Setup

### Requirements

- Git
- Docker Desktop + Docker Compose
- Python 3.12+
- OpenRouter API key

### 1. Clone

```bash
git clone https://github.com/Ravora0809/Signal_post.git
cd signalpost
```

### 2. Configure

```bash
cp .env.example .env
```

Put the OpenRouter key in `.env`. Never commit `.env`.

### 3. Start

```bash
./run.sh