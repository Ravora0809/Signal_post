from dataclasses import dataclass, asdict
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..models import Company, Fact, Source, FactHistory

# Mirrors the challenge's 35/30/20/10/5 weighting without pretending we have
# access to the hidden Builderr/crawler ground truth.
USEFUL_WEIGHTS = {
    "employees": 4.0,
    "industry": 4.0,
    "address": 4.0,
    "city": 2.0,
    "postal_code": 1.0,
    "legal_form": 2.0,
    "phone": 1.0,
    "email": 1.0,
    "website": 1.0,
    "founded_year": 2.0,
    "registration_date": 2.0,
    "industry_code": 2.0,
    "revenue_nok": 3.0,
    "profit_nok": 3.0,
    "capital_nok": 3.0,
}


@dataclass
class CompanyScore:
    orgnr: str
    useful_information_points: float
    identity_evidence_points: float
    update_points: float
    explanation_points: float
    usability_points: float
    overall: float
    verified_fact_count: int
    useful_fact_count: int
    history_count: int


def _value(f: Fact) -> str:
    if f.value_int is not None:
        return str(f.value_int)
    if f.value_num is not None:
        return str(f.value_num)
    return (f.value_text or "").strip().casefold()


def score_company(session: Session, company: Company) -> CompanyScore:
    verified = session.query(Fact).filter(
        Fact.company_id == company.id,
        Fact.verified.is_(True),
    ).all()
    sources = session.query(Source).filter(Source.company_id == company.id).all()
    source_map = {s.id: s for s in sources}
    history = session.query(FactHistory).filter(FactHistory.company_id == company.id).all()

    by_key = {f.key: f for f in verified}

    canonical_useful = {
        "employees", "industry", "address", "city", "postal_code",
        "legal_form", "phone", "email", "website", "founded_year",
        "registration_date", "industry_code", "capital_nok",
    }

    useful_fact_count = len(set(by_key) & canonical_useful)
    if "revenue" in by_key or "revenue_nok" in by_key:
        useful_fact_count += 1
    if "profit" in by_key or "profit_nok" in by_key:
        useful_fact_count += 1

    useful_points = sum(
        USEFUL_WEIGHTS[k]
        for k in by_key
        if k in USEFUL_WEIGHTS
        and k not in {"revenue_nok", "profit_nok"}
    )

    if "revenue" in by_key or "revenue_nok" in by_key:
        useful_points += USEFUL_WEIGHTS["revenue_nok"]
    if "profit" in by_key or "profit_nok" in by_key:
        useful_points += USEFUL_WEIGHTS["profit_nok"]

    useful_points = min(35.0, useful_points)

    # Matching/evidence score: each published fact needs a source tied to the
    # same company, identity verification, and evidence. This is deliberately
    # fact-level rather than merely "one good source = 30 points".
    if verified:
        evidence_ratios = []
        for f in verified:
            src = source_map.get(f.source_id)
            evidence_ratios.append(
                1.0
                if src and src.company_id == company.id and src.identity_verified and f.evidence_snippet
                else 0.0
            )
        identity_evidence_points = 30.0 * (sum(evidence_ratios) / len(evidence_ratios))
    else:
        identity_evidence_points = 0.0

    # A baseline or initial addition is not evidence that change detection has
    # been exercised. Award the extra 10 points only for valid changed/removed
    # events with distinct old/new values. This prevents baseline backfills from
    # artificially inflating the update score.
    real_updates = [h for h in history if h.change_type in {"changed", "removed"}]
    if real_updates:
        valid_updates = [
            h for h in real_updates
            if h.change_type == "removed" and h.old_value is not None
            or h.change_type == "changed"
            and h.old_value is not None
            and h.new_value is not None
            and h.old_value != h.new_value
        ]
        update_points = 10.0 + 10.0 * (len(valid_updates) / len(real_updates))
    elif verified:
        update_points = 10.0
    else:
        update_points = 0.0

    # Explanation score: evidence + source + source date + confidence make the
    # explanation auditable without inventing narrative claims.
    if verified:
        explanation_ratios = []
        for f in verified:
            src = source_map.get(f.source_id)
            ok = bool(
                f.evidence_snippet
                and src
                and src.identity_verified
                and src.url
                and src.fetched_at
                and f.confidence > 0
            )
            explanation_ratios.append(1.0 if ok else 0.0)
        explanation_points = 10.0 * (sum(explanation_ratios) / len(explanation_ratios))
    else:
        explanation_points = 0.0

    # Usability proxy: complete identity + a working source-backed profile.
    usability_points = 5.0 if company.orgnr and company.name and sources and verified else 0.0

    overall = round(
        useful_points + identity_evidence_points + update_points + explanation_points + usability_points,
        2,
    )
    return CompanyScore(
        orgnr=company.orgnr,
        useful_information_points=round(useful_points, 2),
        identity_evidence_points=round(identity_evidence_points, 2),
        update_points=round(update_points, 2),
        explanation_points=round(explanation_points, 2),
        usability_points=round(usability_points, 2),
        overall=overall,
        verified_fact_count=len(verified),
        useful_fact_count=useful_fact_count,
        history_count=len(history),
    )


def evaluate_sample(session: Session, n: int = 100) -> dict:
    total = session.query(func.count(Company.id)).scalar() or 0
    if total == 0:
        return {"error": "no companies in db"}

    companies = session.query(Company).order_by(func.random()).limit(min(n, total)).all()
    scores = [score_company(session, c) for c in companies]
    avg = sum(x.overall for x in scores) / len(scores)

    points = {
        "useful_information": round(sum(x.useful_information_points for x in scores) / len(scores), 2),
        "identity_and_evidence": round(sum(x.identity_evidence_points for x in scores) / len(scores), 2),
        "updates": round(sum(x.update_points for x in scores) / len(scores), 2),
        "explanations": round(sum(x.explanation_points for x in scores) / len(scores), 2),
        "usability": round(sum(x.usability_points for x in scores) / len(scores), 2),
    }

    # Coverage in the challenge is a separate hidden-ground-truth comparison.
    # This is only a local proxy: breadth of useful verified facts among the sample.
    coverage_points = round(points["useful_information"], 2)

    return {
        "sample_size": len(scores),
        "challenge_weighting": "35 useful / 30 identity+evidence / 20 updates / 10 explanations / 5 usability",
        "avg_overall_proxy": round(avg, 2),
        "coverage_proxy_points_out_of_35": coverage_points,
        "coverage_qualifying_threshold": 21.0,
        "target_overall": 65.0,
        "passes_internal_proxy": avg >= 65.0 and coverage_points >= 21.0,
        "ground_truth_note": "The official checked collection is hidden; this local evaluator does not claim to reproduce the official coverage score.",
        "points": points,
        "details": [asdict(x) for x in scores],
    }
