from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from signalpost.db import Base
from signalpost.models import Company, Fact
from signalpost.phases.p6_change_detection import snapshot_previous, detect_changes


def test_changed_fact_is_detected_against_pre_run_snapshot():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    c = Company(orgnr="923609016", name="Example AS")
    s.add(c); s.flush()
    old = Fact(company_id=c.id, key="employees", value_int=100, value_text="100", verified=True, observed_at=datetime(2026, 1, 1))
    s.add(old); s.flush()
    previous = snapshot_previous(s, c.id)
    new = Fact(company_id=c.id, key="employees", value_int=150, value_text="150", verified=True, observed_at=datetime(2026, 2, 1))
    s.add(new); s.flush()
    changes = detect_changes(s, c.id, previous, [new])
    assert len(changes) == 1
    assert changes[0].change_type == "changed"
    assert changes[0].old_value == "100"
    assert changes[0].new_value == "150"
