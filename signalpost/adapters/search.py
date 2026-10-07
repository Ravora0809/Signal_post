from urllib.parse import urlparse
import asyncio
import structlog

log = structlog.get_logger()


class SearchAdapter:
    """Public-web discovery. Search results are candidates until Phase 3 verifies identity."""

    def __init__(self, budget=None, http=None):
        self.budget = budget
        self.http = http

    async def find_official_urls(self, company_name: str, orgnr: str) -> list[str]:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            log.warning("duckduckgo_missing")
            return []

        queries = [
            f'"{company_name}" "{orgnr}" Norway',
            f'"{company_name}" "{orgnr}" annual report',
            f'"{company_name}" "{orgnr}" ansatte',
        ]

        def _search():
            out = []
            seen = set()
            with DDGS() as client:
                for query in queries:
                    try:
                        rows = list(client.text(query, max_results=6) or [])
                    except Exception as exc:
                        log.warning("duckduckgo_query_failed", query=query, error=str(exc))
                        continue
                    for item in rows:
                        url = item.get("href") or item.get("url") if isinstance(item, dict) else None
                        if not url:
                            continue
                        if urlparse(url).scheme not in {"http", "https"}:
                            continue
                        if url not in seen:
                            seen.add(url)
                            out.append(url)
                        if len(out) >= 12:
                            return out
            return out

        try:
            return await asyncio.to_thread(_search)
        except Exception as exc:
            log.warning("duckduckgo_search_failed", error=str(exc))
            return []
