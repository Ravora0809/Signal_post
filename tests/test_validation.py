from datetime import datetime
from signalpost.models import Fact
from signalpost.phases.p5_fact_validation import validate_one


def _mk(key, **kw):
    f = Fact(company_id=1, key=key, observed_at=datetime.utcnow())
    for k, v in kw.items():
        setattr(f, k, v)
    return f


def test_valid_employees():
    f = _mk("employees", value_int=42, value_text="42")
    assert validate_one(f) is True


def test_negative_employees_rejected():
    f = _mk("employees", value_int=-1, value_text="-1")
    assert validate_one(f) is False


def test_founded_year_reasonable():
    assert validate_one(_mk("founded_year", value_int=1999, value_text="1999")) is True
    assert validate_one(_mk("founded_year", value_int=1200, value_text="1200")) is False


def test_email_rule():
    assert validate_one(_mk("email", value_text="a@b.com")) is True
    assert validate_one(_mk("email", value_text="not-an-email")) is False