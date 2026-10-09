from signalpost.phases.p4_fact_extraction import ALLOWED_KEYS
from signalpost.phases.p5_fact_validation import KEY_RULES


def test_total_liabilities_is_the_only_canonical_liability_key():
    assert "total_liabilities" in ALLOWED_KEYS
    assert "debt" not in ALLOWED_KEYS
    assert "total_liabilities" in KEY_RULES
    assert "debt" not in KEY_RULES
