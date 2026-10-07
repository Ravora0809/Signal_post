from signalpost.phases.p4_fact_extraction import deterministic_extract


def test_detects_employees_and_founded():
    text = "Selskapet ble grunnlagt i 2010 og har 45 ansatte."
    facts = deterministic_extract(text)
    keys = {f["key"] for f in facts}
    assert "employees" in keys
    assert "founded_year" in keys


def test_detects_phone_and_email():
    text = "Kontakt: post@firma.no, tlf +47 99887766"
    facts = deterministic_extract(text)
    keys = {f["key"] for f in facts}
    assert "phone" in keys
    assert "email" in keys