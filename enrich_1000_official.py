import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from signalpost.db import session_scope
from signalpost.models import Company, Source, Fact
from signalpost.utils.canonical import canonicalize_url
from signalpost.utils.hashing import sha256_hex, content_hash
from signalpost.phases.p5_fact_validation import validate_and_publish


BASE = "https://data.brreg.no"
ENTITY_URL = BASE + "/enhetsregisteret/api/enheter/{orgnr}"
REGNSKAP_URL = BASE + "/regnskapsregisteret/regnskap/{orgnr}"

ORG_FILE = Path("data/company_numbers_1000.txt")

MAX_COMPANIES = 1000
MAX_REQUESTS = 2000
TIMEOUT = 15
WORKERS = 12

session_http = requests.Session()
session_http.headers.update({
    "User-Agent": "SignalpostBot/1.0 (+public-company-research)",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
})


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def load_orgnrs():
    orgnrs = []

    for line in ORG_FILE.read_text().splitlines():
        org = line.strip()

        if org.isdigit() and len(org) == 9:
            orgnrs.append(org)

    return list(dict.fromkeys(orgnrs))[:MAX_COMPANIES]


def fetch_json(url):
    try:
        r = session_http.get(url, timeout=TIMEOUT)

        if r.status_code != 200:
            return None, r.status_code

        return r.json(), r.status_code

    except Exception as exc:
        print(f"REQUEST ERROR {url}: {exc}")
        return None, None


def upsert_source(session, company, url, kind, body):
    canonical = canonicalize_url(url)
    url_hash = sha256_hex(canonical)
    body_hash = content_hash(body)

    source = (
        session.query(Source)
        .filter(
            Source.company_id == company.id,
            Source.url_hash == url_hash,
        )
        .one_or_none()
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if source is None:
        source = Source(
            company_id=company.id,
            url=url,
            url_canonical=canonical,
            url_hash=url_hash,
            content_hash=body_hash,
            kind=kind,
            status=200,
            body=body,
            identity_verified=True,
            fetched_at=now,
        )

        session.add(source)
        session.flush()

    else:
        source.url = url
        source.url_canonical = canonical
        source.content_hash = body_hash
        source.kind = kind
        source.status = 200
        source.body = body
        source.identity_verified = True
        source.fetched_at = now
        source.rejection_reason = None

        session.flush()

    return source


def fact_value_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def add_fact(
    session,
    company,
    source,
    key,
    value,
    confidence=0.995,
    currency=None,
    as_of=None,
    evidence=None,
):
    if value is None:
        return None

    fact = Fact(
        company_id=company.id,
        key=key,
        source_id=source.id,
        evidence_snippet=evidence or f"Brønnøysundregistrene {key}: {value}",
        confidence=confidence,
        verified=False,
        conflict=False,
        observed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    if isinstance(value, bool):
        fact.value_text = str(value).lower()

    elif isinstance(value, int):
        fact.value_int = value
        fact.value_text = str(value)

    elif isinstance(value, float):
        fact.value_num = value
        fact.value_text = str(value)

    else:
        fact.value_text = str(value).strip()

    if currency:
        fact.currency = currency

    if as_of:
        try:
            fact.as_of = datetime.fromisoformat(
                str(as_of)
            ).replace(tzinfo=None)
        except Exception:
            pass

    session.add(fact)
    session.flush()

    return fact


def make_snippet(body, needle):
    body = body or ""

    idx = body.find(needle)

    if idx < 0:
        return needle

    start = max(0, idx - 180)
    end = min(len(body), idx + len(needle) + 180)

    return body[start:end][:500]


# ---------------------------------------------------------
# Financial extraction
# ---------------------------------------------------------

def extract_regnskap(payload, orgnr, body):
    if not payload:
        return []

    rows = payload if isinstance(payload, list) else [payload]

    candidates = []

    for row in rows:

        if not isinstance(row, dict):
            continue

        company = row.get("virksomhet") or {}

        row_orgnr = str(
            company.get("organisasjonsnummer") or ""
        ).strip()

        if row_orgnr != orgnr:
            continue

        period = row.get("regnskapsperiode") or {}
        end_date = str(period.get("tilDato") or "")

        if end_date:
            candidates.append(row)

    if not candidates:
        return []

    # Prefer company-only accounts
    selskaps = [
        row
        for row in candidates
        if str(row.get("regnskapstype") or "").upper()
        == "SELSKAP"
    ]

    pool = selskaps or candidates

    row = max(
        pool,
        key=lambda x: str(
            (x.get("regnskapsperiode") or {}).get("tilDato") or ""
        ),
    )

    currency = str(
        row.get("valuta") or "NOK"
    ).upper()

    period = row.get("regnskapsperiode") or {}
    end_date = str(period.get("tilDato") or "")

    result = row.get("resultatregnskapResultat") or {}
    operating = result.get("driftsresultat") or {}
    income = operating.get("driftsinntekter") or {}

    equity_debt = row.get("egenkapitalGjeld") or {}
    equity = equity_debt.get("egenkapital") or {}
    debt = equity_debt.get("gjeldOversikt") or {}

    assets = row.get("eiendeler") or {}

    def number(value):
        if isinstance(value, bool):
            return None

        if isinstance(value, (int, float)):
            return value

        try:
            return float(value)
        except Exception:
            return None

    values = [
        (
            "revenue",
            income.get("sumDriftsinntekter"),
            '"sumDriftsinntekter"',
        ),
        (
            "profit",
            result.get("aarsresultat"),
            '"aarsresultat"',
        ),
        (
            "operating_result",
            operating.get("driftsresultat"),
            '"driftsresultat"',
        ),
        (
            "annual_result",
            result.get("aarsresultat"),
            '"aarsresultat"',
        ),
        (
            "total_assets",
            assets.get("sumEiendeler"),
            '"sumEiendeler"',
        ),
        (
            "equity",
            equity.get("sumEgenkapital"),
            '"sumEgenkapital"',
        ),
        (
            "total_liabilities",
            debt.get("sumGjeld"),
            '"sumGjeld"',
        ),
    ]

    facts = []

    for key, raw, evidence_key in values:

        value = number(raw)

        if value is None:
            continue

        value = (
            int(value)
            if float(value).is_integer()
            else float(value)
        )

        # Keep NOK aliases because our evaluator recognizes them.
        if key in {"revenue", "profit"} and currency == "NOK":
            output_key = key + "_nok"
        else:
            output_key = key

        facts.append(
            {
                "key": output_key,
                "value": value,
                "currency": currency,
                "as_of": end_date or None,
                "confidence": 0.995,
                "evidence": make_snippet(
                    body,
                    evidence_key,
                ),
            }
        )

    return facts


# ---------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------

def extract_entity(data, body):

    facts = []

    def add(key, value, json_key):

        if value is None or value == "":
            return

        facts.append(
            {
                "key": key,
                "value": value,
                "confidence": 0.995,
                "evidence": make_snippet(
                    body,
                    json_key,
                ),
            }
        )

    add(
        "employees",
        data.get("antallAnsatte"),
        '"antallAnsatte"',
    )

    industry = data.get("naeringskode1") or {}

    if isinstance(industry, dict):

        add(
            "industry_code",
            industry.get("kode"),
            '"kode"',
        )

        add(
            "industry",
            industry.get("beskrivelse"),
            '"beskrivelse"',
        )

    form = data.get("organisasjonsform") or {}

    if isinstance(form, dict):

        add(
            "legal_form",
            form.get("beskrivelse") or form.get("kode"),
            '"organisasjonsform"',
        )

    address = data.get("forretningsadresse") or {}

    if isinstance(address, dict):

        lines = address.get("adresse") or []

        street = ", ".join(
            str(x).strip()
            for x in lines
            if str(x).strip()
        )

        add(
            "address",
            street,
            '"forretningsadresse"',
        )

        add(
            "postal_code",
            address.get("postnummer"),
            '"postnummer"',
        )

        add(
            "city",
            address.get("poststed"),
            '"poststed"',
        )

    add(
        "website",
        data.get("hjemmeside"),
        '"hjemmeside"',
    )

    add(
        "email",
        data.get("epostadresse"),
        '"epostadresse"',
    )

    add(
        "phone",
        data.get("telefon") or data.get("mobil"),
        '"telefon"',
    )

    founded = str(
        data.get("stiftelsesdato") or ""
    )

    if founded[:4].isdigit():
        add(
            "founded_year",
            int(founded[:4]),
            '"stiftelsesdato"',
        )

    add(
        "registration_date",
        data.get("registreringsdatoEnhetsregisteret"),
        '"registreringsdatoEnhetsregisteret"',
    )

    capital = data.get("kapital") or {}

    if isinstance(capital, dict):

        add(
            "capital_nok",
            capital.get("belop"),
            '"belop"',
        )

    # Only explicit adverse states.
    if data.get("konkurs") is True:
        add(
            "company_status",
            "bankrupt",
            '"konkurs"',
        )

    if data.get("underAvvikling") is True:
        add(
            "company_status",
            "under_liquidation",
            '"underAvvikling"',
        )

    return facts


# ---------------------------------------------------------
# Fetch
# ---------------------------------------------------------

def fetch_company(orgnr):

    entity_url = ENTITY_URL.format(orgnr=orgnr)
    regnskap_url = REGNSKAP_URL.format(orgnr=orgnr)

    entity, entity_status = fetch_json(entity_url)

    regnskap, regnskap_status = fetch_json(regnskap_url)

    return {
        "orgnr": orgnr,
        "entity": entity,
        "entity_status": entity_status,
        "entity_url": entity_url,
        "regnskap": regnskap,
        "regnskap_status": regnskap_status,
        "regnskap_url": regnskap_url,
    }


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():

    orgnrs = load_orgnrs()

    if len(orgnrs) != 1000:
        raise SystemExit(
            f"Expected 1000 org.nrs, found {len(orgnrs)}"
        )

    print("=" * 60)
    print("SIGNALPOST OFFICIAL 1000-COMPANY ENRICHMENT")
    print("=" * 60)

    print(f"Companies : {len(orgnrs)}")
    print("Requests  : 2000 maximum")
    print("Sources   : Brreg entity + Regnskapsregisteret")
    print("LLM       : NO")
    print("Search    : NO")
    print("=" * 60)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:

        futures = {
            pool.submit(fetch_company, org): org
            for org in orgnrs
        }

        completed = 0

        for future in as_completed(futures):

            orgnr = futures[future]

            try:
                result = future.result()

                with session_scope() as session:

                    company = (
                        session.query(Company)
                        .filter(
                            Company.orgnr == orgnr
                        )
                        .one_or_none()
                    )

                    if not company:
                        print(
                            f"[SKIP] {orgnr} not in database"
                        )
                        continue

                    # ---------------------------------
                    # ENTITY
                    # ---------------------------------

                    if isinstance(
                        result["entity"],
                        dict,
                    ):

                        body = json.dumps(
                            result["entity"],
                            ensure_ascii=False,
                        )

                        source = upsert_source(
                            session,
                            company,
                            result["entity_url"],
                            "brreg",
                            body,
                        )

                        facts = extract_entity(
                            result["entity"],
                            body,
                        )

                        # Update company metadata
                        data = result["entity"]

                        company.website = (
                            data.get("hjemmeside")
                            or company.website
                        )

                        for item in facts:
                            add_fact(
                                session,
                                company,
                                source,
                                item["key"],
                                item["value"],
                                item["confidence"],
                                item.get("currency"),
                                item.get("as_of"),
                                item["evidence"],
                            )

                    # ---------------------------------
                    # REGNSKAP
                    # ---------------------------------

                    if result["regnskap"]:

                        body = json.dumps(
                            result["regnskap"],
                            ensure_ascii=False,
                        )

                        source = upsert_source(
                            session,
                            company,
                            result["regnskap_url"],
                            "regnskap",
                            body,
                        )

                        facts = extract_regnskap(
                            result["regnskap"],
                            orgnr,
                            body,
                        )

                        for item in facts:

                            add_fact(
                                session,
                                company,
                                source,
                                item["key"],
                                item["value"],
                                item["confidence"],
                                item.get("currency"),
                                item.get("as_of"),
                                item["evidence"],
                            )

                    session.flush()

                    # Validate provenance + values.
                    fresh_facts = (
                        session.query(Fact)
                        .filter(
                            Fact.company_id == company.id,
                            Fact.verified.is_(False),
                        )
                        .all()
                    )

                    validate_and_publish(
                        session,
                        company.id,
                        fresh_facts,
                    )

                completed += 1

                if completed % 25 == 0:
                    print(
                        f"[{completed}/1000] completed"
                    )

            except Exception as exc:

                print(
                    f"[ERROR] {orgnr}: {exc}"
                )

    print()
    print("=" * 60)
    print("ENRICHMENT COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()