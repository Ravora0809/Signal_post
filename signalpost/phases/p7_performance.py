"""Phase 7: performance, request and cost budget helpers."""
from ..config import get_settings
from ..utils.rate_limit import Budget


def create_budget() -> Budget:
    s = get_settings()
    return Budget(s.max_requests, s.max_runtime_seconds, s.max_cost_usd, s.max_runtime_seconds)


def budget_status(budget: Budget) -> dict:
    return budget.snapshot()
