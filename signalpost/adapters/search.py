from urllib.parse import urlparse
import asyncio
import structlog

log = structlog.get_logger()


class SearchAdapter:
    """Free public-web discovery using DuckDuckGo.

    Search results are candidates only. Every URL is fetched and identity-checked
    by Phase 3 before it can become trusted evidence.
    """

    def __init__(self, budget=None, http=None):
        # Kept injectable for pipeline compatibility; search itself is discovery-only.
        self.budget = budget
        self.http = http

    async def find_official_urls(self, company_name: str, orgnr: str) -> list[str]:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            log.warning("duckduckgo_missing")
            return []

        query = f'"{company_name}" "{orgnr}" Norway'

        def _search():
            return list(DDGS().text(query, max_results=8) or [])

        try:
            results = await asyncio.to_thread(_search)
        except Exception as exc:
            log.warning("duckduckgo_search_failed", error=str(exc))
            return []

        urls, seen = [], set()
        for item in results:
            url = item.get("href") or item.get("url") if isinstance(item, dict) else None
            if not url or urlparse(url).scheme not in {"http", "https"}:
                continue
            if url not in seen:
                seen.add(url)
                urls.append(url)
        return urls
