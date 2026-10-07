import asyncio
import time
from dataclasses import dataclass
import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from ..config import get_settings
from ..utils.ssrf import is_url_safe

log = structlog.get_logger()


@dataclass
class CacheEntry:
    expires_at: float
    response: httpx.Response


class SafeHTTPClient:
    """Async HTTP client with SSRF checks, bounded concurrency, retry and TTL cache."""
    def __init__(self, budget):
        self.budget = budget
        s = get_settings()
        self.cache_ttl = s.http_cache_ttl_seconds
        self._cache: dict[str, CacheEntry] = {}
        self._client = httpx.AsyncClient(
            timeout=s.http_timeout,
            headers={"User-Agent": s.user_agent, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=s.http_concurrency, max_keepalive_connections=s.http_concurrency),
        )
        self._sem = asyncio.Semaphore(s.http_concurrency)

    async def aclose(self):
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def _fetch(self, url: str) -> httpx.Response:
        resp = await self._client.get(url)
        if 500 <= resp.status_code <= 599:
            resp.raise_for_status()
        return resp

    async def get(self, url: str, *, use_cache: bool = True) -> httpx.Response | None:
        ok, reason = is_url_safe(url)
        if not ok:
            log.warning("ssrf_blocked", url=url, reason=reason)
            return None

        now = time.monotonic()
        entry = self._cache.get(url)
        if use_cache and entry and entry.expires_at > now:
            return entry.response
        if entry:
            self._cache.pop(url, None)

        if not self.budget.can_spend(requests=1):
            log.warning("budget_exhausted", url=url, **self.budget.snapshot())
            return None

        async with self._sem:
            try:
                resp = await self._fetch(url)
                self.budget.spend(requests=1)
                if use_cache and resp.status_code == 200:
                    self._cache[url] = CacheEntry(now + self.cache_ttl, resp)
                return resp
            except Exception as e:
                self.budget.spend(requests=1)
                log.warning("http_error", url=url, error=str(e))
                return None
