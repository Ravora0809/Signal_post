
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..models import Fact, Source


KEY_RULES = {
    "employees": {"type": "int", "min": 0, "max": 2_000_000},
    "revenue_nok": {"type": "int", "min": 0, "max": 5_000_000_000_000},
    "profit_nok": {"type": "int", "min": -5_000_000_000_000, "max": 5_000_000_000_000},
    "capital_nok": {"type": "int", "min": 0, "max": 5_000_000_000_000},
    "revenue": {"type": "number", "min": -5_000_000_000_000, "max": 5_000_000_000_000},
    "profit": {"type": "number", "min": -5_000_000_000_000, "max": 5_000_000_000_000},
    "annual_result": {"type": "number", "min": -5_000_000_000_000, "max": 5_000_000_000_000},
    "operating_result": {"type": "number", "min": -5_000_000_000_000, "max": 5_000_000_000_000},
    "total_assets": {"type": "number", "min": 0, "max": 10_000_000_000_000},
    "equity": {"type": "number", "min": -10_000_000_000_000, "max": 10_000_000_000_000},
    "total_liabilities": {"type": "number", "min": 0, "max": 10_000_000_000_000},
    "founded_year": {"type": "int", "min": 1800, "max": datetime.now(timezone.utc).year},
    "registration_date": {"type": "date"},
    "phone": {"type": "phone"},
    "email": {"type": "email"},
    "website": {"type": "url"},
    "postal_code": {"type": "postal"},
}

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
URL_RE = re.compile(r"^https?://", re.I)


def validate_one(fact: Fact) -> bool:
    rule = KEY_RULES.get(fact.key)

    if not rule:
        return bool(
            fact.value_text
            or fact.value_int is not None
            or fact.value_num is not None
        )

    t = rule["type"]

    if t == "int":
        try:
            value = (
                fact.value_int
                if fact.value_int is not None
                else int(str(fact.value_text).replace(",", ""))
            )
        except Exception:
            return False

        if not rule["min"] <= value <= rule["max"]:
            return False

        fact.value_int = value
        fact.value_text = str(value)

    elif t == "number":
        try:
            value = (
                fact.value_num
                if fact.value_num is not None
                else float(str(fact.value_text).replace(",", ""))
            )
        except Exception:
            return False

        if not rule["min"] <= value <= rule["max"]:
            return False

        fact.value_num = value
        fact.value_text = str(value)

    elif t == "email":
        if not fact.value_text or not EMAIL_RE.match(fact.value_text.strip()):
            return False

    elif t == "url":
        if not fact.value_text or not URL_RE.match(fact.value_text.strip()):
            return False

    elif t == "phone":
        digits = re.sub(r"\D", "", fact.value_text or "")
        if not 8 <= len(digits) <= 15:
            return False

    elif t == "postal":
        if not re.match(r"^\d{4}$", fact.value_text or ""):
            return False

    elif t == "date":
        if not fact.value_text or not re.match(
            r"^\d{4}-\d{2}-\d{2}$", fact.value_text.strip()
        ):
            return False

    return True


def _value(fact: Fact) -> str:
    if fact.value_int is not None:
        return str(fact.value_int)
    if fact.value_num is not None:
        return str(fact.value_num)
    return (fact.value_text or "").strip().casefold()


def _source_priority(source: Source | None) -> int:
    """Authority ranking. Higher priority wins before confidence/recency."""
    if source is None:
        return 0

    kind = (source.kind or '').lower()
    path = (source.url or '').split('?', 1)[0].rstrip('/')

    if kind == 'regnskap':
        return 1000

    if kind == 'brreg':
        if '/enhetsregisteret/api/enheter/' in path and not path.endswith('/roller'):
            return 950
        if path.endswith('/roller'):
            return 940
        return 930

    if kind == 'website':
        return 700

    if kind == 'search':
        return 500

    return 100


def _candidate_rank(source: Source | None, fact: Fact) -> tuple:
    return (
        _source_priority(source),
        source.fetched_at if source and source.fetched_at else datetime.min,
        fact.as_of if fact.as_of else datetime.min,
        fact.observed_at if fact.observed_at else datetime.min,
        fact.id or 0,
        float(fact.confidence or 0.0),
    )


_REGNSKAP_EVIDENCE_KEYS = {
    "accounting_currency", "accounting_year", "accounting_statement_type",
    "revenue", "profit", "annual_result", "operating_result",
    "total_assets", "equity", "total_liabilities",
    "revenue_nok", "profit_nok", "capital_nok",
}


def _normalise_evidence(text: str | None) -> str:
    return " ".join((text or "").casefold().split())


def _evidence_supports_fact(fact: Fact, source: Source | None) -> bool:
    """Fail closed when a fact's evidence is not from its attached source.

    For Brreg's structured accounting API, also require the published value to
    occur in that evidence snippet. This prevents a correct value from being
    published alongside a quote copied from a different year/statement record.
    """
    evidence = fact.evidence_snippet or ""
    if not source or not evidence:
        return False

    # The accounting endpoint is structured and must always retain the exact
    # raw source body so record-level evidence can be verified. Preserve the
    # existing compatibility path for non-accounting sources whose body may
    # not be stored by older import/test fixtures.
    if source.kind == "regnskap":
        if not source.body:
            return False
        if _normalise_evidence(evidence) not in _normalise_evidence(source.body):
            return False
        if fact.key in _REGNSKAP_EVIDENCE_KEYS:
            value = _value(fact)
            if not value:
                return False
            # Numeric JSON values may be serialized as e.g. 123.0 while the
            # stored integer is 123; substring matching handles that case.
            if value not in _normalise_evidence(evidence):
                return False
    elif source.body and _normalise_evidence(evidence) not in _normalise_evidence(source.body):
        return False
    return True


def validate_and_publish(session: Session, company_id: int, facts: list[Fact]) -> None:
    """Validate this run and publish exactly one current fact per key.

    Source authority is considered before confidence so an LLM/web observation
    cannot overwrite a newer structured Brreg fact. Older verified rows stay in
    the database for history but are retired from the current published state.
    """
    source_cache: dict[int, Source | None] = {}
    by_key: dict[str, list[Fact]] = {}

    def source_for(fact: Fact) -> Source | None:
        if not fact.source_id:
            return None
        if fact.source_id not in source_cache:
            source_cache[fact.source_id] = (
                session.query(Source)
                .filter(
                    Source.id == fact.source_id,
                    Source.company_id == company_id,
                )
                .one_or_none()
            )
        return source_cache[fact.source_id]

    # Only this run's facts enter candidate selection.
    for fact in facts:
        fact.verified = False
        fact.conflict = False

        if not validate_one(fact):
            continue
        if not fact.source_id or not fact.evidence_snippet:
            continue

        source = source_for(fact)
        if not source or not source.identity_verified:
            continue
        if not _evidence_supports_fact(fact, source):
            continue

        by_key.setdefault(fact.key, []).append(fact)

    for key, candidates in by_key.items():
        if not candidates:
            continue

        ranked = sorted(
            candidates,
            key=lambda fact: _candidate_rank(source_for(fact), fact),
            reverse=True,
        )

        best_priority = _source_priority(source_for(ranked[0]))
        best_authority = [
            fact for fact in ranked
            if _source_priority(source_for(fact)) == best_priority
        ]

        # Fail closed when equally authoritative observations disagree.
        if len({_value(fact) for fact in best_authority}) > 1:
            for fact in candidates:
                fact.conflict = True
            continue

        winner = ranked[0]

        # Retire every previously verified row for this key, except if the
        # candidate is lower authority than the strongest old fact. This protects
        # Brreg data from website/search overwrites.
        old_verified = (
            session.query(Fact)
            .filter(
                Fact.company_id == company_id,
                Fact.key == key,
                Fact.verified.is_(True),
                Fact.id != winner.id,
            )
            .all()
        )

        if old_verified:
            strongest_old = max(
                old_verified,
                key=lambda fact: _candidate_rank(source_for(fact), fact),
            )
            if _candidate_rank(source_for(winner), winner) < _candidate_rank(
                source_for(strongest_old), strongest_old
            ):
                winner.verified = False
                continue

        # Critical freshness invariant: one current published fact per key.
        winner.verified = True
        winner.conflict = False

        for old in old_verified:
            old.verified = False
            old.conflict = False

        for other in candidates:
            if other is not winner:
                other.verified = False

    session.flush()


_ACCOUNTING_BALANCE_KEYS = {"total_assets", "equity", "total_liabilities"}


def accounting_consistency_check(facts: list[Fact]) -> dict:
    """Check assets == equity + liabilities within one selected accounting record.

    Source ID and period are necessary but not sufficient: old facts from a
    previous refresh can share both. Facts must also come from one tight
    observation batch. If the evidence is incomplete, skip the check rather
    than combine facts from separate refreshes. Reported values are never edited.
    """
    base_groups: dict[tuple[int, datetime], list[Fact]] = {}
    allowed_keys = _ACCOUNTING_BALANCE_KEYS | {
        "accounting_currency", "accounting_statement_type", "accounting_year"
    }
    for fact in facts:
        if fact.key not in allowed_keys or fact.source_id is None or fact.as_of is None:
            continue
        base_groups.setdefault((fact.source_id, fact.as_of), []).append(fact)

    # Cluster by observation time (10-second window). All facts emitted from
    # one structured accounting record are persisted together; stale values
    # from earlier refreshes must not fill missing fields in a new record.
    candidates: list[dict[str, Fact]] = []
    for rows in base_groups.values():
        rows.sort(key=lambda f: f.observed_at or datetime.min)
        clusters: list[tuple[datetime, dict[str, Fact]]] = []
        for fact in rows:
            observed = fact.observed_at or datetime.min
            target = next(
                (cluster for anchor, cluster in reversed(clusters)
                 if abs((observed - anchor).total_seconds()) <= 10),
                None,
            )
            if target is None:
                target = {}
                clusters.append((observed, target))
            target[fact.key] = fact
        candidates.extend(cluster for _, cluster in clusters if _ACCOUNTING_BALANCE_KEYS.issubset(cluster))

    if not candidates:
        return {}
    group = max(
        candidates,
        key=lambda g: max((f.observed_at or datetime.min) for f in g.values()),
    )

    def numeric(fact: Fact) -> float | None:
        if fact.value_num is not None:
            return float(fact.value_num)
        if fact.value_int is not None:
            return float(fact.value_int)
        try:
            return float(str(fact.value_text).replace(",", ""))
        except (TypeError, ValueError):
            return None

    assets = numeric(group["total_assets"])
    equity = numeric(group["equity"])
    liabilities = numeric(group["total_liabilities"])
    if assets is None or equity is None or liabilities is None:
        return {}

    difference = assets - (equity + liabilities)
    currency_fact = group.get("accounting_currency")
    currency = (currency_fact.value_text if currency_fact else None) or group["total_assets"].currency or "currency units"
    statement_fact = group.get("accounting_statement_type")
    statement_type = statement_fact.value_text if statement_fact else None
    year_fact = group.get("accounting_year")
    year = year_fact.value_text if year_fact else str(group["total_assets"].as_of.year)
    status = "passed" if abs(difference) <= 1 else "warning"
    if status == "passed":
        message = "Total assets reconcile with equity plus liabilities in the selected accounting record."
    else:
        message = (
            f"Total assets differ from equity plus liabilities by {abs(difference):,.0f} {currency} "
            f"for accounting year {year}. Reported values were preserved; review the original filing."
        )

    return {"balance_sheet": {
        "status": status,
        "accounting_year": year,
        "statement_type": statement_type,
        "currency": currency,
        "total_assets": assets,
        "equity_plus_liabilities": equity + liabilities,
        "difference_assets_minus_equity_and_liabilities": difference,
        "message": message,
    }}
