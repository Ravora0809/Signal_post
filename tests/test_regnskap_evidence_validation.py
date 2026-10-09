from datetime import datetime
from types import SimpleNamespace

from signalpost.phases.p5_fact_validation import _evidence_supports_fact


def test_regnskap_fact_rejected_when_evidence_contains_different_value():
    source = SimpleNamespace(
        kind="regnskap",
        body='[{"regnskapstype":"SELSKAP","regnskapsperiode":{"tilDato":"2025-12-31"},"valuta":"USD","sumDriftsinntekter":67956000000.0}]',
    )
    fact = SimpleNamespace(
        key="revenue", value_int=None, value_num=67_956_000_000.0,
        value_text="67956000000.0",
        evidence_snippet='"regnskapstype":"SELSKAP","regnskapsperiode":{"tilDato":"2025-12-31"},"valuta":"USD","sumDriftsinntekter":107174000000.0',
    )
    assert not _evidence_supports_fact(fact, source)


def test_regnskap_fact_accepted_when_value_is_in_its_source_evidence():
    snippet = '"regnskapstype":"SELSKAP","regnskapsperiode":{"tilDato":"2025-12-31"},"valuta":"USD","sumDriftsinntekter":67956000000.0'
    source = SimpleNamespace(kind="regnskap", body='[{"id":202,' + snippet + '}]')
    fact = SimpleNamespace(
        key="revenue", value_int=None, value_num=67_956_000_000.0,
        value_text="67956000000.0", evidence_snippet=snippet,
        as_of=datetime(2025, 12, 31),
    )
    assert _evidence_supports_fact(fact, source)
