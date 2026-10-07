from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from signalpost.db import Base
from signalpost.models import Company, Source, Fact
from signalpost.phases.p5_fact_validation import validate_and_publish


def test_unresolved_conflict_is_not_published():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine); s = S()
    c = Company(orgnr="923609016", name="Example AS"); s.add(c); s.flush()
    src = Source(company_id=c.id, url="https://x.no", url_canonical="https://x.no", url_hash="a", identity_verified=True)
    s.add(src); s.flush()
    a = Fact(company_id=c.id, key="employees", value_int=10, value_text="10", source_id=src.id, evidence_snippet="10 ansatte", confidence=.7, observed_at=datetime.utcnow())
    b = Fact(company_id=c.id, key="employees", value_int=20, value_text="20", source_id=src.id, evidence_snippet="20 ansatte", confidence=.9, observed_at=datetime.utcnow())
    s.add_all([a,b]); s.flush()
    validate_and_publish(s, c.id, [a,b])
    assert not a.verified and not b.verified
    assert a.conflict and b.conflict
