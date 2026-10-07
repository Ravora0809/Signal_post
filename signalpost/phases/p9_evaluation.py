from dataclasses import dataclass, asdict
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..models import Company, Fact, Source, FactHistory

REQUIRED_KEYS = ["employees", "industry", "address", "revenue_nok", "profit_nok"]

@dataclass
class CompanyScore:
    orgnr: str
    coverage: float
    identity_accuracy: float
    evidence_quality: float
    update_accuracy: float
    overall: float


def score_company(session: Session, company: Company) -> CompanyScore:
    verified = session.query(Fact).filter(Fact.company_id == company.id, Fact.verified.is_(True)).all()
    keys = {f.key for f in verified}
    coverage = len(keys & set(REQUIRED_KEYS)) / len(REQUIRED_KEYS)
    identity_sources = session.query(Source).filter(Source.company_id == company.id).all()
    identity_accuracy = 1.0 if company.name and company.orgnr and identity_sources and any(s.identity_verified for s in identity_sources) else 0.0
    evidence_quality = (sum(bool(f.source_id and f.evidence_snippet) for f in verified) / len(verified)) if verified else 0.0
    history = session.query(FactHistory).filter(FactHistory.company_id == company.id).count()
    update_accuracy = 1.0 if history > 0 or identity_sources else 0.0
    overall = round(100 * (.5 * coverage + .2 * identity_accuracy + .15 * evidence_quality + .15 * update_accuracy), 2)
    return CompanyScore(company.orgnr, coverage, identity_accuracy, evidence_quality, update_accuracy, overall)


def evaluate_sample(session: Session, n: int = 100) -> dict:
    total = session.query(func.count(Company.id)).scalar() or 0
    if total == 0: return {"error": "no companies in db"}
    companies = session.query(Company).order_by(func.random()).limit(min(n, total)).all()
    scores = [score_company(session, c) for c in companies]
    avg = sum(x.overall for x in scores) / len(scores)
    return {"sample_size": len(scores), "avg_overall": round(avg, 2), "target": 65.0, "passes_target": avg >= 65.0, "details": [asdict(x) for x in scores]}
