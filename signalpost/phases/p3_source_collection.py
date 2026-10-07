import re
import structlog
from datetime import datetime, timezone
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from ..adapters.http import SafeHTTPClient
from ..adapters.search import SearchAdapter
from ..models import Company, Source
from ..utils.canonical import canonicalize_url
from ..utils.hashing import sha256_hex, content_hash

log = structlog.get_logger()
STATIC_SOURCES_TEMPLATE = [
    "https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
    "https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}/roller",
]


def _name_tokens(name: str) -> set[str]:
    stop = {"as", "asa", "nuf", "the", "and", "og"}
    return {x for x in re.findall(r"[a-z0-9æøå]+", name.lower()) if len(x) >= 3 and x not in stop}


def verify_source_identity(company: Company, url: str, body: str, kind: str) -> tuple[bool, str]:
    if kind == "brreg":
        return True, "trusted_brreg"
    if not body:
        return False, "empty_body"
    low = body.lower()
    signals = 0
    if company.orgnr and company.orgnr in body:
        signals += 2
    tokens = _name_tokens(company.name)
    if tokens and sum(1 for t in tokens if t in low) >= max(1, min(2, len(tokens))):
        signals += 1
    official_host = urlparse(company.website or "").hostname
    source_host = urlparse(url).hostname
    if official_host and source_host and official_host.lower().removeprefix("www.") == source_host.lower().removeprefix("www."):
        signals += 2
    if signals >= 2:
        return True, "identity_verified"
    return False, "company_identity_not_proven"


def _store(session: Session, company: Company, url: str, kind: str, status: int | None, body: str | None, identity_verified: bool, rejection_reason: str | None = None) -> Source | None:
    canon = canonicalize_url(url)
    uh = sha256_hex(canon)
    existing = session.query(Source).filter_by(company_id=company.id, url_hash=uh).one_or_none()
    ch = content_hash(body) if body else None
    if existing is None:
        src = Source(company_id=company.id, url=url, url_canonical=canon, url_hash=uh,
                     content_hash=ch, kind=kind, status=status, body=body,
                     fetched_at=datetime.now(timezone.utc).replace(tzinfo=None), identity_verified=identity_verified,
                     rejection_reason=rejection_reason)
        session.add(src)
        session.flush()
        return src
    existing.fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    existing.status = status
    existing.body = body
    existing.content_hash = ch
    existing.identity_verified = identity_verified
    existing.rejection_reason = rejection_reason
    session.flush()
    return existing


async def collect(session: Session, http: SafeHTTPClient, search: SearchAdapter, company: Company) -> list[Source]:
    urls: list[tuple[str, str]] = [(t.format(orgnr=company.orgnr), "brreg") for t in STATIC_SOURCES_TEMPLATE]
    if company.website:
        urls.append((company.website, "website"))
    urls.extend((u, "search") for u in await search.find_official_urls(company.name, company.orgnr))

    seen: set[str] = set()
    sources: list[Source] = []
    for url, kind in urls:
        key = canonicalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        resp = await http.get(url, use_cache=True)
        if resp is None:
            continue
        body = resp.text[:500_000] if resp.status_code == 200 else None
        verified, reason = verify_source_identity(company, url, body or "", kind)
        src = _store(session, company, url, kind, resp.status_code, body if verified else None, verified, None if verified else reason)
        if src and verified:
            sources.append(src)
        elif src:
            log.warning("source_rejected", orgnr=company.orgnr, url=url, reason=reason)
    return sources
