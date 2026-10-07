from types import SimpleNamespace
from signalpost.phases.p3_source_collection import verify_source_identity


def test_identity_accepts_orgnr():
    company = SimpleNamespace(name="Example AS", orgnr="923609016", website="https://example.no")
    assert verify_source_identity(company, "https://example.no", "Org.nr 923609016 Example AS", "website")[0]


def test_identity_rejects_unrelated_site():
    company = SimpleNamespace(name="Example AS", orgnr="923609016", website="https://example.no")
    assert verify_source_identity(company, "https://other.no", "Welcome to an unrelated company", "search")[0] is False
