from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from .db import get_session_factory
from .pipeline import SignalPostPipeline
from .models import Company, Fact, FactHistory, Source
from .phases.p2_database import database_health
from .phases.p9_evaluation import evaluate_sample
from .phases.p8_bulk_profiles import run_bulk

app = FastAPI(title="Signalpost", version="1.0.0")


class ResearchRequest(BaseModel):
    company_number: str = Field(..., min_length=9, max_length=9)


class BulkRequest(BaseModel):
    company_numbers: list[str] = Field(..., min_length=1, max_length=1000)


@app.get("/health")
def health():
    session = get_session_factory()()
    try:
        return database_health(session)
    finally:
        session.close()


@app.post("/research")
async def research(request: ResearchRequest):
    pipeline = SignalPostPipeline()
    session = get_session_factory()()
    try:
        result = await pipeline.research_one(session, request.company_number)
        if result.get("status") == "not_found":
            session.commit()
            raise HTTPException(status_code=404, detail=result)
        if result.get("status") == "error":
            session.rollback()
            raise HTTPException(status_code=500, detail=result)
        session.commit()
        return result
    finally:
        session.close()
        await pipeline.aclose()


@app.get("/companies/{orgnr}")
def company_profile(orgnr: str):
    session = get_session_factory()()
    try:
        company = session.query(Company).filter_by(orgnr=orgnr).one_or_none()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        facts = session.query(Fact).filter(Fact.company_id == company.id, Fact.verified.is_(True)).order_by(Fact.key).all()
        return {"orgnr": company.orgnr, "name": company.name, "website": company.website,
                "facts": [{"key": f.key, "value": f.value_text, "source_id": f.source_id,
                            "evidence": f.evidence_snippet, "observed_at": f.observed_at} for f in facts]}
    finally:
        session.close()


@app.get("/companies/{orgnr}/sources")
def company_sources(orgnr: str):
    session = get_session_factory()()
    try:
        company = session.query(Company).filter_by(orgnr=orgnr).one_or_none()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        sources = session.query(Source).filter_by(company_id=company.id).order_by(Source.fetched_at.desc()).all()
        return {"orgnr": orgnr, "sources": [{"url": s.url, "kind": s.kind, "status": s.status,
                "identity_verified": s.identity_verified, "fetched_at": s.fetched_at,
                "content_hash": s.content_hash, "rejection_reason": s.rejection_reason} for s in sources]}
    finally:
        session.close()


@app.get("/companies/{orgnr}/history")
def company_history(orgnr: str):
    session = get_session_factory()()
    try:
        company = session.query(Company).filter_by(orgnr=orgnr).one_or_none()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        rows = session.query(FactHistory).filter_by(company_id=company.id).order_by(FactHistory.detected_at.desc()).all()
        return {"orgnr": orgnr, "changes": [{"key": r.key, "old": r.old_value, "new": r.new_value,
                "type": r.change_type, "detected_at": r.detected_at} for r in rows]}
    finally:
        session.close()


@app.post("/evaluate")
def evaluate(sample_size: int = 100):
    session = get_session_factory()()
    try:
        return evaluate_sample(session, n=max(1, min(sample_size, 100)))
    finally:
        session.close()


@app.post("/bulk-research")
async def bulk_research(request: BulkRequest):
    pipeline = SignalPostPipeline()
    try:
        return await run_bulk(get_session_factory(), pipeline, request.company_numbers, concurrency=4)
    finally:
        await pipeline.aclose()
