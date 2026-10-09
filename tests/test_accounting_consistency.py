from datetime import datetime
from types import SimpleNamespace

from signalpost.phases.p5_fact_validation import accounting_consistency_check


def fact(key, value, *, source_id=7, as_of=None, currency=None):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = None
    return SimpleNamespace(
        key=key,
        value_text=str(value),
        value_int=None,
        value_num=numeric,
        source_id=source_id,
        as_of=as_of or datetime(2025, 12, 31),
        currency=currency,
        observed_at=datetime(2026, 1, 1),
    )


def test_balance_sheet_reconciles():
    facts = [
        fact("total_assets", 1000),
        fact("equity", 400),
        fact("total_liabilities", 600),
        fact("accounting_currency", "NOK"),
        fact("accounting_statement_type", "SELSKAP"),
        fact("accounting_year", 2025),
    ]
    result = accounting_consistency_check(facts)["balance_sheet"]
    assert result["status"] == "passed"
    assert result["difference_assets_minus_equity_and_liabilities"] == 0


def test_balance_sheet_discrepancy_warns_without_adjusting_values():
    facts = [
        fact("total_assets", 104_520_000_000),
        fact("equity", 33_173_000_000),
        fact("total_liabilities", 71_345_000_000),
        fact("accounting_currency", "NOK"),
        fact("accounting_statement_type", "SELSKAP"),
        fact("accounting_year", 2025),
    ]
    result = accounting_consistency_check(facts)["balance_sheet"]
    assert result["status"] == "warning"
    assert result["difference_assets_minus_equity_and_liabilities"] == 2_000_000
    assert result["total_assets"] == 104_520_000_000
    assert "Reported values were preserved" in result["message"]


def test_balance_sheet_never_combines_values_from_different_sources():
    facts = [
        fact("total_assets", 1000, source_id=1),
        fact("equity", 400, source_id=1),
        fact("total_liabilities", 600, source_id=2),
    ]
    assert accounting_consistency_check(facts) == {}


def test_balance_sheet_does_not_mix_stale_values_from_a_previous_refresh():
    facts = [
        fact("total_assets", 1000, source_id=1, as_of=datetime(2025, 12, 31)),
        fact("equity", 400, source_id=1, as_of=datetime(2025, 12, 31)),
        fact("total_liabilities", 600, source_id=1, as_of=datetime(2025, 12, 31)),
    ]
    # The liability fact is stale relative to the two new observations.
    facts[0].observed_at = datetime(2026, 1, 2, 12, 0, 1)
    facts[1].observed_at = datetime(2026, 1, 2, 12, 0, 2)
    facts[2].observed_at = datetime(2026, 1, 2, 11, 0, 0)
    assert accounting_consistency_check(facts) == {}
