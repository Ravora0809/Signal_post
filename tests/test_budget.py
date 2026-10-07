from signalpost.utils.rate_limit import Budget


def test_request_budget():
    b = Budget(max_requests=2, max_runtime_seconds=2700, max_cost_usd=10)
    assert b.can_spend(1)
    b.spend(2)
    assert not b.can_spend(1)


def test_cost_budget():
    b = Budget(max_requests=10, max_runtime_seconds=2700, max_cost_usd=1)
    b.spend(cost=.9)
    assert not b.can_spend(cost=.2)
