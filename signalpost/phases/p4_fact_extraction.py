import re
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from ..adapters.llm import LLMAdapter
from ..models import Company, Source, Fact

ALLOWED_KEYS = [
    "employees", "industry", "address", "city", "postal_code", "revenue_nok", "profit_nok",
    "founded_year", "phone", "email", "website", "legal_form", "chair", "ceo",
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


def evidence_is_grounded(body: str, evidence: str) -> bool:
    if not evidence or len(evidence.strip()) < 3:
        return False
    compact_body = " ".join(body.lower().split())
    compact_ev = " ".join(evidence.lower().split())
    return compact_ev in compact_body


async def extract_from_source(llm: LLMAdapter, source: Source) -> tuple[list[dict], float]:
    if not source.body or not source.identity_verified:
        return [], 0.0
    llm_facts, cost = await llm.extract_facts(source.body, ALLOWED_KEYS)
    det_facts = deterministic_extract(source.body)
    by_key: dict[str, dict] = {}
    for f in det_facts:
        by_key.setdefault(f["key"], f)
    for f in llm_facts:
        k = f.get("key")
        ev = (f.get("evidence") or "")[:500]
        if k in ALLOWED_KEYS and evidence_is_grounded(source.body, ev):
            by_key[k] = {"key": k, "value": f.get("value"), "confidence": max(0.0, min(1.0, float(f.get("confidence", .7)))), "evidence": ev}
    return list(by_key.values()), cost


def persist_facts(session: Session, company: Company, source: Source, facts: list[dict]) -> list[Fact]:
    stored = []
    for f in facts:
        key, val = f["key"], f.get("value")
        fact = Fact(company_id=company.id, key=key, source_id=source.id, evidence_snippet=f.get("evidence"),
                    confidence=float(f.get("confidence", .5)), observed_at=datetime.now(timezone.utc).replace(tzinfo=None))
        if isinstance(val, bool):
            fact.value_text = str(val).lower()
        elif isinstance(val, int):
            fact.value_int, fact.value_text = val, str(val)
        elif isinstance(val, float):
            fact.value_num, fact.value_text = val, str(val)
        elif val is not None:
            fact.value_text = str(val).strip()
        if key in {"revenue_nok", "profit_nok"}:
            fact.currency = "NOK"
        session.add(fact)
        stored.append(fact)
    session.flush()
    return stored
