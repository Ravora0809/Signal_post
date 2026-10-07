from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from signalpost.models import Base, Company, Fact, Source
from signalpost.phases.p9_evaluation import score_company


def test_challenge_score_rewards_verified_useful_facts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        company = Company(orgnr="984851006", name="DNB BANK ASA")
        session.add(company)
        session.flush()
        source = Source(
            company_id=company.id,
            url="https://data.brreg.no/enhetsregisteret/api/enheter/984851006",
            url_canonical="https://data.brreg.no/enhetsregisteret/api/enheter/984851006",
            url_hash="a" * 64,
            kind="brreg",
            status=200,
            body='{"navn":"DNB BANK ASA"}',
            identity_verified=True,
            fetched_at=datetime.utcnow(),
        )
        session.add(source)
        session.flush()
        for key, value in {
            "employees": "7353",
            "industry": "Banker",
            "address": "Dronning Eufemias gate 30",
            "city": "OSLO",
            "postal_code": "0191",
            "legal_form": "Aksjeselskap",
            "website": "https://dnb.no",
            "phone": "+47 91504800",
            "founded_year": "2002",
        }.items():
            session.add(Fact(
                company_id=company.id,
                key=key,
                value_text=value,
                source_id=source.id,
                evidence_snippet=f"Brreg {key}: {value}",
                confidence=.99,
                verified=True,
                observed_at=datetime.utcnow(),
            ))
        session.flush()
        score = score_company(session, company)
        assert score.useful_information_points >= 20
        assert score.identity_evidence_points == 30
        assert score.explanation_points == 10
        assert score.usability_points == 5
        assert score.overall >= 75
