from signalpost.phases.p4_fact_extraction import structured_financial_web_extract


class SourceStub:
    url = "https://sokfirma.no/selskap/984851006/dnb-bank-asa"


def test_dnb_financial_web_table_is_tied_to_year_and_unit():
    body = """
    Dnb Bank ASA Org.nr 984851006
    Regnskap 2024-12
    Beløp i NOK 1000
    Sum driftsinntekter 86 537 000
    Driftsresultat (EBIT) 44 078 000
    Årsresultat 35 004 000
    Sum eiendeler 3 036 892 000
    Sum egenkapital 233 322 000
    """
    facts = structured_financial_web_extract(body, SourceStub())
    got = {f["key"]: f for f in facts}
    assert got["accounting_year"]["value"] == 2024
    assert got["accounting_currency"]["value"] == "NOK"
    assert got["revenue_nok"]["value"] == 86_537_000_000
    assert got["operating_result"]["value"] == 44_078_000_000
    assert got["annual_result"]["value"] == 35_004_000_000
    assert got["total_assets"]["value"] == 3_036_892_000_000
    assert got["equity"]["value"] == 233_322_000_000
    assert got["revenue_nok"]["as_of"] == "2024-12-31"
