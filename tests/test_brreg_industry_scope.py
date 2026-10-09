import json
from signalpost.phases.p4_fact_extraction import structured_brreg_extract


class SourceStub:
    url = "https://data.brreg.no/enhetsregisteret/api/enheter/986228608"


def test_primary_and_auxiliary_industry_codes_are_separate():
    body = json.dumps({
        "organisasjonsnummer": "986228608",
        "naeringskode1": {"kode": "20.150", "beskrivelse": "Produksjon av gjødsel og nitrogenforbindelser"},
        "hjelpeenhetskode": {"kode": "70.100", "beskrivelse": "Hovedkontortjenester"},
        "antallAnsatte": 536,
        "registreringsdatoAntallAnsatteEnhetsregisteret": "2026-09-14",
    }, ensure_ascii=False)
    facts = structured_brreg_extract(body, SourceStub())
    by_key = {fact["key"]: fact for fact in facts}
    assert by_key["industry_code"]["value"] == "20.150"
    assert by_key["industry"]["value"] == "Produksjon av gjødsel og nitrogenforbindelser"
    assert by_key["auxiliary_industry_code"]["value"] == "70.100"
    assert by_key["auxiliary_industry"]["value"] == "Hovedkontortjenester"
    assert by_key["employees"]["as_of"] == "2026-09-14"
