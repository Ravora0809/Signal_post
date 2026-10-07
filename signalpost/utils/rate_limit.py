import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Budget:
    max_requests: int
    max_runtime_seconds: int
    max_cost_usd: float
    window_seconds: int = 2700
    started_at: float = field(default_factory=time.monotonic)
    requests: int = 0
    cost_usd: float = 0.0
    _request_times: deque = field(default_factory=deque)

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.window_seconds
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

    def can_spend(self, requests: int = 1, cost: float = 0.0) -> bool:
        self._prune()
        return (
            len(self._request_times) + requests <= self.max_requests
            and self.cost_usd + cost <= self.max_cost_usd
            and self.elapsed() <= self.max_runtime_seconds
        )

    def spend(self, requests: int = 1, cost: float = 0.0) -> None:
        if requests:
            now = time.monotonic()
            for _ in range(requests):
                self._request_times.append(now)
        self.requests += requests
        self.cost_usd += cost

    def snapshot(self) -> dict:
        self._prune()
        return {
            "requests_total": self.requests,
            "requests_in_window": len(self._request_times),
            "max_requests_in_window": self.max_requests,
            "cost_usd": round(self.cost_usd, 6),
            "max_cost_usd": self.max_cost_usd,
            "elapsed_s": round(self.elapsed(), 2),
            "max_runtime_s": self.max_runtime_seconds,
        }
