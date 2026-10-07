import re
import structlog
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from ..adapters.http import SafeHTTPClient
from ..models import Company

log = structlog.get_logger()

ORGNR_RE = re.compile(r"^\d{9}$")
BRREG_URL = "https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}"

# Modulus-11 checksum used by Norwegian org.nr
def _checksum_ok(orgnr: str) -> bool:
    digits = [int(c) for c in orgnr]
    weights = [3, 2, 7, 6, 5, 4, 3, 2]
    s = sum(d * w for d, w in zip(digits[:8], weights))
    k = 11 - (s % 11)
    if k == 11:
        k = 0
    if k == 10:
        return False
    return k == digits[8]


def validate_orgnr(orgnr: str) -> bool:
    return bool(ORGNR_RE.match(orgnr)) and _checksum_ok(orgnr)


async def fetch_company(http: SafeHTTPClient, orgnr: str) -> dict | None:
    if not validate_orgnr(orgnr):
        log.warning("invalid_orgnr", orgnr=orgnr)
        return None
    resp = await http.get(BRREG_URL.format(orgnr=orgnr))
    if resp is None or resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def upsert_company(session: Session, orgnr: str, data: dict) -> Company:
    company = session.query(Company).filter_by(orgnr=orgnr).one_or_none()
    if company is None:
        company = Company(orgnr=orgnr, name=data.get("navn", ""))
        session.add(company)

    company.name = data.get("navn", company.name)
    company.legal_form = (data.get("organisasjonsform") or {}).get("kode") or company.legal_form
    company.registration_date = data.get("registreringsdatoEnhetsregisteret") or company.registration_date

    naics = data.get("naeringskode1") or {}
    company.industry_code = naics.get("kode") or company.industry_code
    company.industry_label = naics.get("beskrivelse") or company.industry_label

    addr = data.get("forretningsadresse") or {}
    company.address = ", ".join(addr.get("adresse", [])) or company.address
    company.postal_code = addr.get("postnummer") or company.postal_code
    company.city = addr.get("poststed") or company.city

    website = data.get("hjemmeside")
    if website:
        company.website = website

    company.raw = data
    company.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.flush()
    return company


async def run(session: Session, http: SafeHTTPClient, orgnr: str) -> Company | None:
    data = await fetch_company(http, orgnr)
    if not data:
        return None
    return upsert_company(session, orgnr, data)