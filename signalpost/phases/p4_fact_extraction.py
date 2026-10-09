import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..adapters.llm import LLMAdapter
from ..models import Company, Source, Fact

ALLOWED_KEYS = [
    "employees", "industry", "industry_code", "address", "city", "postal_code",
    "revenue_nok", "profit_nok", "capital_nok", "revenue", "profit",
    "annual_result", "operating_result", "total_assets", "equity", "total_liabilities",
    "accounting_currency", "accounting_year", "accounting_statement_type", "founded_year", "registration_date",
    "phone", "email", "website", "legal_form", "chair", "ceo", "company_status",
    "purpose", "activity", "sector", "latest_accounts_year",
    "auxiliary_industry", "auxiliary_industry_code",
]

PY_EMPLOYEES = re.compile(r"(\d{1,9})\s+(?:ansatte|employees|medarbeidere)", re.I)
PY_MONEY = re.compile(r"(?:omsetning|revenue|profit|resultat)[^\d]{0,30}(\d[\d\s.,]{0,30})\s*(million(?:er)?|mrd|milliard(?:er)?|kr|nok)", re.I)
PY_FOUNDED = re.compile(r"(?:grunnlagt|etablert|founded)[^\d]{0,20}(\d{4})", re.I)
PY_PHONE = re.compile(r"(?:\+47|0047)[\s-]?(\d{2}[\s-]?\d{2}[\s-]?\d{2}[\s-]?\d{2})")
PY_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PY_POSTAL = re.compile(r"\b(\d{4})\s+[A-Za-zÆØÅæøå .-]{2,}\b")


def _money_value(raw: str, unit: str) -> int | None:
    text = raw.strip().replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        tail = text.rsplit(",", 1)[1]
        text = text.replace(",", ".") if len(tail) <= 2 else text.replace(",", "")
    elif "." in text:
        tail = text.rsplit(".", 1)[1]
        if len(tail) == 3 and text.count(".") == 1:
            text = text.replace(".", "")
    try:
        value = float(text)
    except ValueError:
        return None
    u = unit.lower()
    if u.startswith("million"):
        value *= 1_000_000
    elif u in {"mrd", "milliard", "milliarder"}:
        value *= 1_000_000_000
    return int(round(value))


def deterministic_extract(text: str) -> list[dict]:
    facts: list[dict] = []
    for m in PY_EMPLOYEES.finditer(text):
        facts.append({"key": "employees", "value": int(m.group(1)), "confidence": .65, "evidence": m.group(0)})
    for m in PY_MONEY.finditer(text):
        key = "profit_nok" if re.search(r"profit|resultat", m.group(0), re.I) else "revenue_nok"
        value = _money_value(m.group(1), m.group(2))
        if value is not None:
            facts.append({"key": key, "value": value, "confidence": .62, "evidence": m.group(0)})
    for m in PY_FOUNDED.finditer(text):
        facts.append({"key": "founded_year", "value": int(m.group(1)), "confidence": .65, "evidence": m.group(0)})
    for m in PY_PHONE.finditer(text):
        facts.append({"key": "phone", "value": "+47 " + re.sub(r"\D", "", m.group(1)), "confidence": .7, "evidence": m.group(0)})
    for m in PY_EMAIL.finditer(text):
        facts.append({"key": "email", "value": m.group(0), "confidence": .7, "evidence": m.group(0)})
    for m in PY_POSTAL.finditer(text):
        facts.append({"key": "postal_code", "value": m.group(1), "confidence": .5, "evidence": m.group(0)})
    return facts


def _snippet(body: str, needle: str, radius: int = 220) -> str:
    """Return an exact substring from the stored body for audit-friendly evidence."""
    idx = body.find(needle)
    if idx < 0:
        idx = body.lower().find(needle.lower())
    if idx < 0:
        return needle[:500]
    start = max(0, idx - radius)
    end = min(len(body), idx + len(needle) + radius)
    return body[start:end][:500]


def _as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except Exception:
        return None


def structured_brreg_extract(body: str, source: Source) -> list[dict]:
    try:
        data = json.loads(body)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []

    path = urlparse(source.url).path.rstrip("/")
    if path.endswith("/roller"):
        return []

    facts: list[dict] = []

    def add(key: str, value, confidence: float = .99, json_key: str | None = None, as_of: str | None = None):
        if value in (None, "", [], {}):
            return
        if isinstance(value, list):
            value = ", ".join(str(x) for x in value if x not in (None, ""))
        facts.append({
            "key": key,
            "value": value,
            "confidence": confidence,
            "evidence": _snippet(body, json_key or key),
            "as_of": as_of,
        })

    employee_as_of = data.get(
        "registreringsdatoAntallAnsatteEnhetsregisteret"
    )
    add(
        "employees",
        data.get("antallAnsatte"),
        json_key='"antallAnsatte"',
        as_of=employee_as_of,
    )

    # naeringskode1 is the primary industry classification. Keep the
    # auxiliary-unit code separate so a headquarters-services code is never
    # mistaken for the company's main industry.
    industry = data.get("naeringskode1") or {}
    if isinstance(industry, dict):
        add("industry_code", industry.get("kode"), json_key='"naeringskode1"')
        add("industry", industry.get("beskrivelse"), json_key='"naeringskode1"')

    auxiliary_industry = data.get("hjelpeenhetskode") or {}
    if isinstance(auxiliary_industry, dict):
        add("auxiliary_industry_code", auxiliary_industry.get("kode"), json_key='"hjelpeenhetskode"')
        add("auxiliary_industry", auxiliary_industry.get("beskrivelse"), json_key='"hjelpeenhetskode"')

    form = data.get("organisasjonsform") or {}
    if isinstance(form, dict):
        add("legal_form", form.get("beskrivelse") or form.get("kode"), json_key='"organisasjonsform"')

    addr = data.get("forretningsadresse") or {}
    if isinstance(addr, dict):
        lines = addr.get("adresse") or []
        address = ", ".join(str(x).strip() for x in lines if str(x).strip())
        add("address", address, json_key='"forretningsadresse"')
        add("postal_code", addr.get("postnummer"), json_key='"postnummer"')
        add("city", addr.get("poststed"), json_key='"poststed"')

    add("website", data.get("hjemmeside"), json_key='"hjemmeside"')
    add("email", data.get("epostadresse"), json_key='"epostadresse"')
    add("phone", data.get("telefon") or data.get("mobil"), json_key='"telefon"')

    founded = str(data.get("stiftelsesdato") or "")
    if re.match(r"^\d{4}", founded):
        add("founded_year", int(founded[:4]), json_key='"stiftelsesdato"')

    add("registration_date", data.get("registreringsdatoEnhetsregisteret"), json_key='"registreringsdatoEnhetsregisteret"')
    latest_accounts = str(data.get("sisteInnsendteAarsregnskap") or "")
    if re.match(r"^\d{4}$", latest_accounts):
        add("latest_accounts_year", int(latest_accounts), json_key='"sisteInnsendteAarsregnskap"')
    add("purpose", data.get("vedtektsfestetFormaal"), json_key='"vedtektsfestetFormaal"')
    add("activity", data.get("aktivitet"), json_key='"aktivitet"')

    sector = data.get("institusjonellSektorkode") or {}
    if isinstance(sector, dict):
        add("sector", sector.get("beskrivelse") or sector.get("kode"), json_key='"institusjonellSektorkode"')

    capital = data.get("kapital") or {}
    if isinstance(capital, dict):
        add("capital_nok", capital.get("belop"), json_key='"belop"')

    # Company status is deterministic and comes only from Brreg lifecycle flags.
    # Never ask the LLM to infer status.
    konkurs = data.get("konkurs") is True
    under_avvikling = data.get("underAvvikling") is True
    under_tvang = data.get("underTvangsavviklingEllerTvangsopplosning") is True
    if konkurs:
        status = "bankrupt"
        status_key = '"konkurs"'
    elif under_avvikling:
        status = "under_liquidation"
        status_key = '"underAvvikling"'
    elif under_tvang:
        status = "under_forced_dissolution"
        status_key = '"underTvangsavviklingEllerTvangsopplosning"'
    else:
        status = "active"
        status_key = '"konkurs"'
    add("company_status", status, confidence=.999, json_key=status_key)

    return facts


def _json_record_slice(body: str, target: dict) -> str | None:
    """Return the exact source substring for one parsed JSON record.

    Searching the whole endpoint response for a field name is unsafe because
    Brreg returns multiple years and statement types in one payload. Evidence
    must come from the exact selected record, not the first occurrence anywhere
    in the response.
    """
    try:
        decoder = json.JSONDecoder()
        start = len(body) - len(body.lstrip())
        if start >= len(body):
            return None
        if body[start] != "[":
            parsed, end = decoder.raw_decode(body, start)
            return body[start:end] if parsed == target else None

        pos = start + 1
        while pos < len(body):
            while pos < len(body) and (body[pos].isspace() or body[pos] == ","):
                pos += 1
            if pos >= len(body) or body[pos] == "]":
                break
            record_start = pos
            record, pos = decoder.raw_decode(body, pos)
            if record == target:
                return body[record_start:pos]
        return None
    except (ValueError, TypeError):
        return None


def structured_regnskap_extract(body: str, source: Source) -> list[dict]:
    # Parse Brreg annual-account JSON.
    try:
        payload = json.loads(body)
    except Exception:
        return []

    rows = payload if isinstance(payload, list) else [payload]
    orgnr = (urlparse(source.url).path.rstrip("/").split("/")[-1] or "").strip()

    candidates: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        virksomhet = row.get("virksomhet") or {}
        row_orgnr = str(virksomhet.get("organisasjonsnummer") or "").strip()
        if row_orgnr != orgnr:
            continue

        period = row.get("regnskapsperiode") or {}
        if str(period.get("tilDato") or ""):
            candidates.append(row)

    if not candidates:
        return []

    # Prefer company-only accounts (SELSKAP) over consolidated accounts
    # (KONSERN), then choose the newest accounting period.
    selskaps = [
        row for row in candidates
        if str(row.get("regnskapstype") or "").upper() == "SELSKAP"
    ]
    pool = selskaps or candidates
    pool.sort(
        key=lambda row: str(
            (row.get("regnskapsperiode") or {}).get("tilDato") or ""
        ),
        reverse=True,
    )
    row = pool[0]

    # Critical evidence invariant: all fields and evidence are scoped to this
    # one selected accounting record. If we cannot locate its exact raw JSON
    # slice in the source response, publish no financial facts from this source.
    row_body = _json_record_slice(body, row)
    if not row_body:
        return []

    currency = str(row.get("valuta") or "").upper().strip()
    statement_type = str(row.get("regnskapstype") or "").upper().strip()
    period = row.get("regnskapsperiode") or {}
    end_date = str(period.get("tilDato") or "")
    year = int(end_date[:4]) if re.match(r"^\d{4}", end_date) else None

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

    def snippet_for(term: str) -> str:
        # Search only the selected record, never the entire multi-record body.
        idx = row_body.find(term)
        if idx < 0:
            idx = row_body.lower().find(term.lower())
        if idx < 0:
            return ""
        start = max(0, idx - 220)
        end = min(len(row_body), idx + len(term) + 220)
        return row_body[start:end][:500]

    facts: list[dict] = []

    if statement_type:
        evidence = snippet_for('"regnskapstype"')
        if evidence:
            facts.append({
                "key": "accounting_statement_type",
                "value": statement_type,
                "confidence": 0.995,
                "evidence": evidence,
                "as_of": end_date,
            })

    if currency:
        evidence = snippet_for('"valuta"')
        if evidence:
            facts.append({
                "key": "accounting_currency",
                "value": currency,
                "confidence": 0.995,
                "evidence": evidence,
                "as_of": end_date,
            })

    if year is not None:
        evidence = snippet_for('"tilDato"')
        if evidence:
            facts.append({
                "key": "accounting_year",
                "value": year,
                "confidence": 0.995,
                "evidence": evidence,
                "as_of": end_date,
            })

    values = [
        ("revenue", income.get("sumDriftsinntekter"), '"sumDriftsinntekter"'),
        ("profit", result.get("aarsresultat"), '"aarsresultat"'),
        ("operating_result", operating.get("driftsresultat"), '"driftsresultat"'),
        ("annual_result", result.get("aarsresultat"), '"aarsresultat"'),
        ("total_assets", assets.get("sumEiendeler"), '"sumEiendeler"'),
        ("equity", equity.get("sumEgenkapital"), '"sumEgenkapital"'),
        ("total_liabilities", debt.get("sumGjeld"), '"sumGjeld"'),
    ]

    for key, raw_value, evidence_key in values:
        value = number(raw_value)
        if value is None:
            continue

        clean_value = int(value) if float(value).is_integer() else float(value)
        out_key = (
            key + "_nok"
            if key in {"revenue", "profit"} and currency == "NOK"
            else key
        )

        evidence = snippet_for(evidence_key)
        if not evidence or str(raw_value) not in evidence:
            # Fail closed if the exact selected-record value is not visible in
            # the evidence snippet. Never publish a value without proof.
            continue
        facts.append({
            "key": out_key,
            "value": clean_value,
            "confidence": 0.995,
            "evidence": evidence,
            "currency": currency or None,
            "as_of": end_date,
        })

    return facts


def structured_financial_web_extract(body: str, source: Source) -> list[dict]:
    """Extract financial facts from a single, identity-verified public filing.

    Sources are deliberately split into two cases:
    - Proff/Sokfirma: tabular company figures, usually explicitly labelled as
      parent/company accounts.
    - FinancialFilings: searchable mirror of the annual report.  For a group
      report we MUST isolate the ``Annual accounts DNB Bank ASA`` section before
      reading numbers, otherwise group figures could be published for the
      company.  If that section is not present, return no company-level facts.

    The accounting year is the reporting year, while ``as_of`` is the financial
    statement end date.  Publication/fetch date is kept on Source.fetched_at and
    is not confused with the accounting period.
    """
    url = (source.url or '').lower()
    if not any(host in url for host in ("proff.no", "sokfirma.no", "financialfilings.com")):
        return []

    text = body or ""
    scope = text
    scope_label = "company_financial_table"

    if "financialfilings.com" in url:
        marker = re.search(r"Annual accounts DNB Bank ASA", text, re.I)
        if not marker:
            # Generic company filing pages can still contain an explicit
            # company annual-accounts heading.
            marker = re.search(r"Annual accounts\s+[A-Z][A-Za-z0-9 .,&-]{2,120}", text, re.I)
        if not marker:
            return []
        scope = text[marker.start():]
        # Stop before the next major report section. This prevents the parser
        # from falling back into the Group accounts later in the document.
        nxt = re.search(r"\n\s*#\s+(?:Statement|Independent auditor|Appendix|Notes to the accounts)\b", scope, re.I)
        if nxt and nxt.start() > 100:
            scope = scope[:nxt.start()]
        scope_label = "annual_report_company_accounts"

    # Prefer the accounting table header over publication/crawl dates.
    # Annual reports are often published in the following calendar year (e.g.
    # 2025 accounts published in March 2026), so using max(year) is unsafe.
    header = re.search(
        r"(?:regnskap[^\n]{0,80}?|amounts\s+in\s+NOK[^\n]{0,80}?|\b20\d{2}-12-31[^\n]{0,20}?)"
        r"(20\d{2})",
        scope, re.I,
    )
    if header:
        year = int(header.group(1))
    else:
        year_candidates = [int(y) for y in re.findall(r"\b(20\d{2})\b", scope[:5000])]
        if not year_candidates:
            return []
        year = max(y for y in year_candidates if y <= datetime.now(timezone.utc).year)
    end_date = f"{year}-12-31"

    currency = "NOK" if re.search(r"\bNOK\b", scope, re.I) else None
    thousands = bool(re.search(r"bel[øo]p\s+i\s+(?:NOK\s+)?1000|amounts\s+in\s+NOK\s+thousand", scope, re.I))
    millions = bool(re.search(r"amounts\s+in\s+NOK\s+million", scope, re.I))

    def parse_num(raw: str, unit: str = "") -> float | None:
        x = raw.strip().replace(" ", "")
        # Parentheses are presentation negatives in annual reports.
        negative = x.startswith("(") and x.endswith(")")
        x = x.strip("()")
        if "," in x and "." in x:
            x = x.replace(".", "").replace(",", ".")
        elif "," in x:
            x = x.replace(",", ".")
        try:
            n = float(x)
        except ValueError:
            return None
        u = unit.lower()
        if "mrd" in u or "billion" in u or "milliard" in u:
            n *= 1_000_000_000
        elif "million" in u:
            n *= 1_000_000
        elif thousands:
            n *= 1_000
        elif millions:
            n *= 1_000_000
        if negative:
            n = -n
        return n

    # In report tables the first numeric value after a row label is the latest
    # accounting year. We intentionally do NOT use generic "resultat" because
    # that can match a different row such as Resultat før skatt.
    patterns = [
        ("revenue_nok", r"(?:sum\s+driftsinntekter|total\s+income)\s*[:|]?\s*\(?([0-9][0-9\s.,]*)\)?\s*(mrd(?:\.?\s*kr)?|billion(?:\s*kr)?|milliard(?:er)?(?:\s*kr)?|million(?:er)?(?:\s*kr)?|kr)?"),
        ("operating_result", r"(?:driftsresultat\s*\(?(?:EBIT)?\)?|pre-tax\s+operating\s+profit)\s*[:|]?\s*\(?([0-9][0-9\s.,]*)\)?\s*(mrd(?:\.?\s*kr)?|billion(?:\s*kr)?|milliard(?:er)?(?:\s*kr)?|million(?:er)?(?:\s*kr)?|kr)?"),
        ("annual_result", r"(?:årsresultat|aarsresultat|profit\s+for\s+the\s+year)\s*[:|]?\s*\(?([0-9][0-9\s.,]*)\)?\s*(mrd(?:\.?\s*kr)?|billion(?:\s*kr)?|milliard(?:er)?(?:\s*kr)?|million(?:er)?(?:\s*kr)?|kr)?"),
        ("total_assets", r"(?:sum\s+eiendeler|total\s+assets)\s*[:|]?\s*\(?([0-9][0-9\s.,]*)\)?\s*(mrd(?:\.?\s*kr)?|billion(?:\s*kr)?|milliard(?:er)?(?:\s*kr)?|million(?:er)?(?:\s*kr)?|kr)?"),
        ("equity", r"(?:sum\s+egenkapital|total\s+equity)\s*[:|]?\s*\(?([0-9][0-9\s.,]*)\)?\s*(mrd(?:\.?\s*kr)?|billion(?:\s*kr)?|milliard(?:er)?(?:\s*kr)?|million(?:er)?(?:\s*kr)?|kr)?"),
        ("total_liabilities", r"(?:sum\s+gjeld|total\s+liabilities)\s*[:|]?\s*\(?([0-9][0-9\s.,]*)\)?\s*(mrd(?:\.?\s*kr)?|billion(?:\s*kr)?|milliard(?:er)?(?:\s*kr)?|million(?:er)?(?:\s*kr)?|kr)?"),
    ]

    facts = [{
        "key": "accounting_year", "value": year, "confidence": 0.995,
        "evidence": f"{scope_label}: accounting year {year}", "as_of": end_date,
    }]
    if currency:
        facts.append({"key": "accounting_currency", "value": currency, "confidence": 0.995, "evidence": "NOK", "as_of": end_date})

    for out_key, pattern in patterns:
        m = re.search(pattern, scope, re.I)
        if not m:
            continue
        value = parse_num(m.group(1), m.group(2) or "")
        if value is None:
            continue
        evidence = scope[max(0, m.start()-140):min(len(scope), m.end()+140)].strip()[:700]
        facts.append({
            "key": out_key, "value": int(value) if value.is_integer() else value,
            "confidence": 0.995, "evidence": evidence, "currency": currency, "as_of": end_date,
        })
    return facts


async def extract_from_source(llm: LLMAdapter, source: Source) -> tuple[list[dict], float]:
    if not source.body or not source.identity_verified:
        return [], 0.0

    by_key: dict[str, dict] = {}

    if source.kind == "brreg":
        deterministic = structured_brreg_extract(source.body, source)
        # /roller is intentionally handled with the LLM because role payloads
        # are heterogeneous; core entity JSON stays deterministic.
        if deterministic:
            for f in deterministic:
                by_key[f["key"]] = f

    elif source.kind == "regnskap":
        for f in structured_regnskap_extract(source.body, source):
            by_key[f["key"]] = f

    else:
        for f in deterministic_extract(source.body):
            by_key.setdefault(f["key"], f)
        for f in structured_financial_web_extract(source.body, source):
            by_key[f["key"]] = f

    # Only enrich non-registry sources and the role endpoint through the LLM.
    # Never let an LLM overwrite a higher-confidence structured Brreg fact.
    should_llm = source.kind not in {"regnskap"} and (
        source.kind != "brreg" or urlparse(source.url).path.rstrip("/").endswith("/roller")
    )
    cost = 0.0
    if should_llm:
        llm_facts, cost = await llm.extract_facts(source.body, ALLOWED_KEYS)
        if source.kind == "brreg" and urlparse(source.url).path.rstrip("/").endswith("/roller"):
            protected = {
                "employees", "industry", "industry_code", "address",
                "city", "postal_code", "legal_form", "phone",
                "email", "website", "registration_date", "founded_year",
            }
            llm_facts = [f for f in llm_facts if f.get("key") not in protected]
        body_low = " ".join(source.body.lower().split())
        for f in llm_facts:
            k = f.get("key")
            ev = (f.get("evidence") or "")[:500]
            if k not in ALLOWED_KEYS or len(ev.strip()) < 3:
                continue
            if " ".join(ev.lower().split()) not in body_low:
                continue
            candidate = {
                "key": k,
                "value": f.get("value"),
                "confidence": max(0.0, min(1.0, float(f.get("confidence", .7)))),
                "evidence": ev,
            }
            existing = by_key.get(k)
            if existing is None or candidate["confidence"] > float(existing.get("confidence", 0)):
                by_key[k] = candidate

    # A few providers return a zero confidence even when the extracted value
    # is directly supported by an exact quote from an identity-verified source.
    # Repair only the known deterministic cases; do not inflate arbitrary LLM
    # outputs or treat confidence as a calibrated probability.
    source_path = urlparse(source.url).path.rstrip("/")
    source_host = (urlparse(source.url).hostname or "").lower()
    for fact in by_key.values():
        try:
            confidence = float(fact.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        evidence = str(fact.get("evidence") or "")
        value = str(fact.get("value") or "")
        exact_evidence = bool(evidence and source.body and evidence in source.body)
        if confidence > 0 or not source.identity_verified or not exact_evidence:
            continue
        key = fact.get("key")
        if source.kind == "brreg" and source_path.endswith("/roller") and key in {"ceo", "chair"}:
            fact["confidence"] = 0.90
        elif source.kind == "website" and key == "website":
            value_host = (urlparse(value if value.startswith(("http://", "https://")) else "https://" + value).hostname or "").lower()
            if source_host and value_host and (source_host == value_host or source_host.endswith("." + value_host) or value_host.endswith("." + source_host)):
                fact["confidence"] = 0.90

    return list(by_key.values()), cost


def persist_facts(session: Session, company: Company, source: Source, facts: list[dict]) -> list[Fact]:
    stored = []
    for f in facts:
        key, val = f["key"], f.get("value")
        fact = Fact(
            company_id=company.id,
            key=key,
            source_id=source.id,
            evidence_snippet=f.get("evidence"),
            confidence=float(f.get("confidence", .5)),
            observed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        if isinstance(val, bool):
            fact.value_text = str(val).lower()
        elif isinstance(val, int):
            fact.value_int, fact.value_text = val, str(val)
        elif isinstance(val, float):
            fact.value_num, fact.value_text = val, str(val)
        elif val is not None:
            fact.value_text = str(val).strip()

        if key in {"revenue_nok", "profit_nok", "capital_nok", "revenue", "profit", "annual_result", "operating_result", "total_assets", "equity", "total_liabilities"}:
            fact.currency = f.get("currency") or ("NOK" if key.endswith("_nok") or key == "capital_nok" else None)

        as_of = f.get("as_of")
        if as_of:
            try:
                fact.as_of = datetime.fromisoformat(str(as_of)).replace(tzinfo=None)
            except ValueError:
                pass

        session.add(fact)
        stored.append(fact)
    session.flush()
    return stored
