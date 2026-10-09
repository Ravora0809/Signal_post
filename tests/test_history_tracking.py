import csv
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from signalpost.db import Base
from signalpost.models import Company, Fact, FactHistory, Source
from signalpost.phases.p6_change_detection import snapshot_previous, detect_changes
from signalpost.phases.p8_registry_import import import_registry_csv
from signalpost.phases.p9_evaluation import score_company


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_numeric_change_is_detected_and_missing_extraction_is_not_removal():
    session = make_session()
    company = Company(orgnr="923609016", name="Example AS")
    session.add(company)
    session.flush()
    old = Fact(
        company_id=company.id,
        key="employees",
        value_int=100,
        value_text="100",
        verified=True,
        observed_at=datetime(2026, 1, 1),
    )
    session.add(old)
    session.flush()
    previous = snapshot_previous(session, company.id)
    new = Fact(
        company_id=company.id,
        key="employees",
        value_int=150,
        value_text="150.0",
        verified=True,
        observed_at=datetime(2026, 2, 1),
    )
    session.add(new)
    session.flush()

    changes = detect_changes(session, company.id, previous, [new])
    assert len(changes) == 1
    assert changes[0].change_type == "changed"
    assert changes[0].old_value == "100"
    assert changes[0].new_value == "150"

    # Missing extraction output is not an explicit removal.
    previous = snapshot_previous(session, company.id)
    assert detect_changes(session, company.id, previous, []) == []
    session.close()


def write_registry_csv(path, employees):
    columns = [
        "organisasjonsnummer", "navn", "organisasjonsform.beskrivelse",
        "registreringsdatoenhetsregisteret", "naeringskode1.kode",
        "naeringskode1.beskrivelse", "antallAnsatte", "hjemmeside",
        "epostadresse", "telefon", "mobil", "forretningsadresse.adresse",
        "forretningsadresse.postnummer", "forretningsadresse.kommune",
        "forretningsadresse.landkode", "institusjonellSektorkode.beskrivelse",
        "registreringsdatoAntallAnsatteEnhetsregisteret", "stiftelsesdato",
        "sisteInnsendteAarsregnskap", "vedtektsfestetFormaal", "aktivitet",
        "kapital.belop", "konkurs", "underAvvikling",
        "underTvangsavviklingEllerTvangsopplosning",
    ]
    row = {
        "organisasjonsnummer": "923609016",
        "navn": "Example AS",
        "organisasjonsform.beskrivelse": "Aksjeselskap",
        "registreringsdatoenhetsregisteret": "2001-01-01",
        "naeringskode1.kode": "62.010",
        "naeringskode1.beskrivelse": "IT services",
        "antallAnsatte": str(employees),
        "hjemmeside": "https://example.no",
        "forretningsadresse.adresse": "Testgata 1",
        "forretningsadresse.postnummer": "0123",
        "forretningsadresse.kommune": "Oslo",
        "forretningsadresse.landkode": "NO",
        "registreringsdatoAntallAnsatteEnhetsregisteret": "2026-09-14",
        "stiftelsesdato": "2001-01-01",
        "sisteInnsendteAarsregnskap": "2025",
        "kapital.belop": "30000",
        "konkurs": "false",
        "underAvvikling": "false",
        "underTvangsavviklingEllerTvangsopplosning": "false",
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(row)


def test_registry_import_records_real_change_and_baselines_legacy_state(tmp_path):
    session = make_session()
    csv_path = tmp_path / "brreg.csv"
    orgnr_path = tmp_path / "orgnrs.txt"
    orgnr_path.write_text("923609016\n", encoding="utf-8")

    write_registry_csv(csv_path, 100)
    first = import_registry_csv(session, csv_path, orgnr_path)
    assert first["errors"] == 0
    company = session.query(Company).filter_by(orgnr="923609016").one()
    first_history = session.query(FactHistory).filter_by(company_id=company.id).all()
    assert any(h.key == "employees" and h.change_type == "added" for h in first_history)

    # Simulate a pre-history profile: remove ledger entries, keep current facts.
    session.query(FactHistory).filter_by(company_id=company.id).delete()
    session.commit()
    write_registry_csv(csv_path, 100)
    import_registry_csv(session, csv_path, orgnr_path)
    assert session.query(FactHistory).filter_by(
        company_id=company.id, change_type="baseline"
    ).count() > 0

    write_registry_csv(csv_path, 125)
    import_registry_csv(session, csv_path, orgnr_path)
    change = session.query(FactHistory).filter_by(
        company_id=company.id, key="employees", change_type="changed"
    ).order_by(FactHistory.id.desc()).first()
    assert change is not None
    assert change.old_value == "100"
    assert change.new_value == "125"

    current = session.query(Fact).filter_by(
        company_id=company.id, key="employees", verified=True
    ).all()
    assert len(current) == 1
    assert current[0].value_text == "125"
    session.close()


def test_baseline_history_does_not_fake_full_update_score():
    session = make_session()
    company = Company(orgnr="923609016", name="Example AS")
    session.add(company)
    session.flush()
    source = Source(
        company_id=company.id,
        url="https://example.no",
        url_canonical="https://example.no",
        url_hash="abc",
        identity_verified=True,
    )
    session.add(source)
    session.flush()
    fact = Fact(
        company_id=company.id, key="employees", value_int=10, value_text="10",
        source_id=source.id, evidence_snippet="10 employees", confidence=1.0,
        verified=True,
    )
    session.add(fact)
    session.add(FactHistory(
        company_id=company.id, key="employees", old_value=None,
        new_value="10", change_type="baseline",
    ))
    session.flush()
    score = score_company(session, company)
    assert score.update_points == 10.0

    session.add(FactHistory(
        company_id=company.id, key="employees", old_value="10",
        new_value="12", change_type="changed",
    ))
    session.flush()
    score = score_company(session, company)
    assert score.update_points == 20.0
    session.close()


def test_cross_source_value_difference_is_reconciled_not_counted_as_change(tmp_path):
    session = make_session()
    company = Company(orgnr="923609016", name="Example AS")
    session.add(company)
    session.flush()
    old_source = Source(
        company_id=company.id, url="https://data.brreg.no/api/enheter/923609016",
        url_canonical="https://data.brreg.no/api/enheter/923609016",
        url_hash="old-source", kind="brreg", identity_verified=True,
    )
    session.add(old_source)
    session.flush()
    session.add(Fact(
        company_id=company.id, key="industry", value_text="Oil and gas; refining",
        source_id=old_source.id, evidence_snippet="old registry schema",
        confidence=1.0, verified=True, observed_at=datetime(2026, 1, 1),
    ))
    session.commit()

    csv_path = tmp_path / "brreg.csv"
    orgnr_path = tmp_path / "orgnrs.txt"
    orgnr_path.write_text("923609016\n", encoding="utf-8")
    write_registry_csv(csv_path, 100)
    # Ensure incoming feed contains the same semantic key with a differently
    # shaped label, like a legacy aggregate industry label vs primary industry.
    import_registry_csv(session, csv_path, orgnr_path)
    event = session.query(FactHistory).filter_by(
        company_id=company.id, key="industry", old_value="oil and gas; refining"
    ).order_by(FactHistory.id.desc()).first()
    assert event is not None
    assert event.change_type == "reconciled"

    # A subsequent change from the same Brreg CSV feed is a real update.
    write_registry_csv(csv_path, 125)
    import_registry_csv(session, csv_path, orgnr_path)
    employee_change = session.query(FactHistory).filter_by(
        company_id=company.id, key="employees", change_type="changed"
    ).order_by(FactHistory.id.desc()).first()
    assert employee_change is not None
    assert employee_change.old_value == "100"
    assert employee_change.new_value == "125"
    session.close()
