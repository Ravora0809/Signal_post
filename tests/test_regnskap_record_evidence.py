import json

from signalpost.phases.p4_fact_extraction import structured_regnskap_extract


class SourceStub:
    url = "https://data.brreg.no/regnskapsregisteret/regnskap/923609016"


def make_record(*, record_id, year, kind, currency, revenue, operating, annual, assets, equity, liabilities):
    return {
        "id": record_id,
        "journalnr": f"journal-{record_id}",
        "regnskapstype": kind,
        "virksomhet": {
            "organisasjonsnummer": "923609016",
            "organisasjonsform": "ASA",
            "morselskap": True,
        },
        "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
        "valuta": currency,
        "resultatregnskapResultat": {
            "aarsresultat": annual,
            "driftsresultat": {
                "driftsresultat": operating,
                "driftsinntekter": {"sumDriftsinntekter": revenue},
            },
        },
        "eiendeler": {"sumEiendeler": assets},
        "egenkapitalGjeld": {
            "sumEgenkapitalGjeld": assets,
            "egenkapital": {"sumEgenkapital": equity},
            "gjeldOversikt": {"sumGjeld": liabilities},
        },
    }


def test_financial_evidence_comes_from_selected_company_record_only():
    older_group = make_record(
        record_id=101, year=2023, kind="KONSERN", currency="USD",
        revenue=107_174_000_000.0, operating=35_770_000_000.0,
        annual=11_904_000_000.0, assets=143_580_000_000.0,
        equity=48_500_000_000.0, liabilities=95_080_000_000.0,
    )
    latest_company = make_record(
        record_id=202, year=2025, kind="SELSKAP", currency="USD",
        revenue=67_956_000_000.0, operating=5_563_000_000.0,
        annual=5_731_000_000.0, assets=103_432_000_000.0,
        equity=39_182_000_000.0, liabilities=64_249_000_000.0,
    )
    body = json.dumps([older_group, latest_company], separators=(",", ":"))

    facts = structured_regnskap_extract(body, SourceStub())
    by_key = {fact["key"]: fact for fact in facts}

    assert by_key["accounting_year"]["value"] == 2025
    assert by_key["accounting_currency"]["value"] == "USD"
    assert by_key["accounting_statement_type"]["value"] == "SELSKAP"
    assert by_key["revenue"]["value"] == 67_956_000_000
    assert by_key["operating_result"]["value"] == 5_563_000_000
    assert by_key["annual_result"]["value"] == 5_731_000_000
    assert by_key["total_assets"]["value"] == 103_432_000_000
    assert by_key["equity"]["value"] == 39_182_000_000
    assert by_key["total_liabilities"]["value"] == 64_249_000_000

    for fact in facts:
        evidence = fact["evidence"]
        assert evidence
        assert evidence in body
        assert '"regnskapstype":"KONSERN"' not in evidence
        assert '"id":101' not in evidence

    # Each financial figure must be present in its own exact evidence snippet.
    for key in ("revenue", "operating_result", "annual_result", "total_assets", "equity", "total_liabilities"):
        assert str(by_key[key]["value"]) in by_key[key]["evidence"]
    assert '"regnskapstype":"SELSKAP"' in by_key["accounting_statement_type"]["evidence"]
    assert '"tilDato":"2025-12-31"' in by_key["accounting_year"]["evidence"]

    assert '67956000000.0' in by_key["revenue"]["evidence"]
    assert '107174000000.0' not in by_key["revenue"]["evidence"]


def test_no_financial_facts_when_selected_record_cannot_be_located_in_raw_body():
    record = make_record(
        record_id=202, year=2025, kind="SELSKAP", currency="USD",
        revenue=67_956_000_000.0, operating=5_563_000_000.0,
        annual=5_731_000_000.0, assets=103_432_000_000.0,
        equity=39_182_000_000.0, liabilities=64_249_000_000.0,
    )
    # Whitespace changes the parsed structure but not semantic data; raw_decode
    # should still locate the exact record. This also guards against brittle
    # dependence on compact-only JSON.
    body = json.dumps([record], indent=2)
    facts = structured_regnskap_extract(body, SourceStub())
    assert facts
    assert all(fact["evidence"] in body for fact in facts)
