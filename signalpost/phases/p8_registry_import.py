import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Company, Source, Fact, FactHistory


BRREG_DATASET_URL = (
    "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv"
)


FACT_COLUMNS = {
    "legal_form": "organisasjonsform.beskrivelse",
    "industry_code": "naeringskode1.kode",
    "industry": "naeringskode1.beskrivelse",
    "employees": "antallAnsatte",
    "website": "hjemmeside",
    "email": "epostadresse",
    "phone": "telefon",
    "mobile": "mobil",
    "address": "forretningsadresse.adresse",
    "city": "forretningsadresse.kommune",
    "postal_code": "forretningsadresse.postnummer",
    "country": "forretningsadresse.landkode",
    "sector": "institusjonellSektorkode.beskrivelse",
    "registration_date": "registreringsdatoenhetsregisteret",
    "founded_year": "stiftelsesdato",
    "latest_accounts_year": "sisteInnsendteAarsregnskap",
    "purpose": "vedtektsfestetFormaal",
    "activity": "aktivitet",
    "capital_nok": "kapital.belop",
}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def clean(value):
    if value is None:
        return None

    value = str(value).strip()

    if not value or value.lower() in {"nan", "none", "null"}:
        return None

    return value


def canonical_url(url: str) -> str:
    return url.strip().rstrip("/")


def url_hash(url: str) -> str:
    return hashlib.sha256(
        canonical_url(url).encode("utf-8")
    ).hexdigest()


def row_hash(row: dict) -> str:
    payload = "|".join(
        f"{k}={clean(row.get(k)) or ''}"
        for k in sorted(row.keys())
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def evidence(column: str, value: str) -> str:
    return f"Brreg CSV column `{column}` = `{value}`"


def value_for_fact(key: str, value: str):
    if key == "employees":
        try:
            return None, int(float(value))
        except ValueError:
            return None, None

    if key == "capital_nok":
        try:
            return float(
                value.replace(" ", "").replace(",", ".")
            ), None
        except ValueError:
            return None, None

    if key == "founded_year":
        try:
            return None, int(value[:4])
        except (ValueError, TypeError):
            return None, None

    return None, None


def canonical_fact_value(fact: Fact) -> str:
    if fact.value_int is not None:
        return str(int(fact.value_int))
    if fact.value_num is not None:
        number = float(fact.value_num)
        return str(int(number)) if number.is_integer() else format(number, ".15g")
    return (fact.value_text or "").strip().casefold()


def canonical_incoming_value(raw_value: str, value_num, value_int) -> str:
    if value_int is not None:
        return str(int(value_int))
    if value_num is not None:
        number = float(value_num)
        return str(int(number)) if number.is_integer() else format(number, ".15g")
    return (raw_value or "").strip().casefold()


def record_baseline_if_needed(session: Session, company_id: int) -> int:
    """Record a clearly labelled baseline for legacy profiles lacking history.

    Baseline rows establish what was already stored when history tracking was
    introduced. They are not treated as proof that a change was detected.
    """
    has_history = session.query(FactHistory.id).filter(
        FactHistory.company_id == company_id
    ).first()
    if has_history:
        return 0
    current = session.query(Fact).filter(
        Fact.company_id == company_id,
        Fact.verified.is_(True),
    ).order_by(Fact.observed_at.desc(), Fact.id.desc()).all()
    latest = {}
    for fact in current:
        latest.setdefault(fact.key, fact)
    rows = [
        FactHistory(
            company_id=company_id,
            key=key,
            old_value=None,
            new_value=canonical_fact_value(fact),
            change_type="baseline",
        )
        for key, fact in latest.items()
    ]
    if rows:
        session.add_all(rows)
        session.flush()
    return len(rows)


def upsert_registry_fact(
    session: Session,
    company: Company,
    source: Source,
    key: str,
    raw_value: str,
    column: str,
    value_num=None,
    value_int=None,
    as_of: str | None = None,
) -> bool:
    """Persist one current Brreg fact and append real history when it changes."""
    incoming = canonical_incoming_value(raw_value, value_num, value_int)
    previous = session.query(Fact).filter(
        Fact.company_id == company.id,
        Fact.key == key,
        Fact.verified.is_(True),
    ).order_by(Fact.observed_at.desc(), Fact.id.desc()).first()

    if previous and canonical_fact_value(previous) == incoming:
        # Same value: refresh the current observation/evidence without creating
        # a fake history event. Avoid another row when this exact source/value
        # is already present and current.
        if previous.source_id == source.id:
            previous.observed_at = utcnow()
            previous.evidence_snippet = evidence(column, raw_value)
            previous.confidence = 1.0
            if as_of:
                try:
                    previous.as_of = datetime.fromisoformat(as_of).replace(tzinfo=None)
                except ValueError:
                    pass
            return False
        # Keep a new provenance observation but retire the older duplicate.
        previous.verified = False
    elif previous:
        old_value = canonical_fact_value(previous)
        previous_source = session.query(Source).filter(
            Source.id == previous.source_id,
            Source.company_id == company.id,
        ).one_or_none() if previous.source_id else None
        previous_kind = previous_source.kind if previous_source else None
        previous.verified = False
        # Do not call a cross-source/schema reconciliation a real-world update.
        # Only comparable observations from the same authoritative feed can
        # establish a change. The values are retained for audit either way.
        event_type = "changed" if previous_kind == source.kind == "brreg_csv" else "reconciled"
        session.add(FactHistory(
            company_id=company.id,
            key=key,
            old_value=old_value,
            new_value=incoming,
            change_type=event_type,
        ))
    else:
        # If there is no verified current value, this is the first published
        # value in the current ledger (not a fabricated update).
        session.add(FactHistory(
            company_id=company.id,
            key=key,
            old_value=None,
            new_value=incoming,
            change_type="added",
        ))

    fact = Fact(
        company_id=company.id,
        key=key,
        value_text=raw_value,
        value_num=value_num,
        value_int=value_int,
        source_id=source.id,
        evidence_snippet=evidence(column, raw_value),
        confidence=1.0,
        verified=True,
        conflict=False,
        observed_at=utcnow(),
    )
    if as_of:
        try:
            fact.as_of = datetime.fromisoformat(as_of).replace(tzinfo=None)
        except ValueError:
            pass
    session.add(fact)
    return True


def import_registry_csv(
    session: Session,
    csv_path: str | Path,
    orgnr_path: str | Path,
) -> dict:

    csv_path = Path(csv_path)
    orgnr_path = Path(orgnr_path)

    target_orgnrs = {
        line.strip()
        for line in orgnr_path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    }

    imported = 0
    updated = 0
    skipped = 0
    errors = 0
    facts_created = 0

    source_url = canonical_url(BRREG_DATASET_URL)
    source_hash = url_hash(source_url)

    with csv_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as fh:

        reader = csv.DictReader(fh)

        for row in reader:

            orgnr = clean(row.get("organisasjonsnummer"))

            if not orgnr or orgnr not in target_orgnrs:
                continue

            try:
                name = clean(row.get("navn"))

                if not name:
                    skipped += 1
                    continue

                company = (
                    session.query(Company)
                    .filter(Company.orgnr == orgnr)
                    .one_or_none()
                )
                company_was_existing = company is not None

                if company is None:
                    company = Company(
                        orgnr=orgnr,
                        name=name,
                        country="NO",
                    )
                    session.add(company)
                    session.flush()
                    imported += 1
                else:
                    updated += 1

                # Establish a one-time baseline for legacy rows created before
                # change history was enabled. Baseline entries are not scored as
                # detected changes by the evaluator.
                if company_was_existing:
                    record_baseline_if_needed(session, company.id)

                # -------------------------------------------------
                # Update Company directly from authoritative Brreg
                # -------------------------------------------------

                company.name = name

                company.legal_form = clean(
                    row.get("organisasjonsform.beskrivelse")
                )

                company.registration_date = clean(
                    row.get("registreringsdatoenhetsregisteret")
                )

                company.industry_code = clean(
                    row.get("naeringskode1.kode")
                )

                company.industry_label = clean(
                    row.get("naeringskode1.beskrivelse")
                )

                company.address = clean(
                    row.get("forretningsadresse.adresse")
                )

                company.postal_code = clean(
                    row.get("forretningsadresse.postnummer")
                )

                company.city = clean(
                    row.get("forretningsadresse.kommune")
                )

                company.website = clean(
                    row.get("hjemmeside")
                )

                company.country = (
                    clean(
                        row.get("forretningsadresse.landkode")
                    )
                    or "NO"
                )

                company.raw = {
                    "source": "brreg_enhetsregisteret_csv",
                    "dataset_url": BRREG_DATASET_URL,
                    "orgnr": orgnr,
                    "row_hash": row_hash(row),
                }

                company.updated_at = utcnow()

                session.flush()

                # -------------------------------------------------
                # Source
                # -------------------------------------------------

                source = (
                    session.query(Source)
                    .filter(
                        Source.company_id == company.id,
                        Source.url_hash == source_hash,
                    )
                    .one_or_none()
                )

                if source is None:
                    source = Source(
                        company_id=company.id,
                        url=source_url,
                        url_canonical=source_url,
                        url_hash=source_hash,
                        kind="brreg_csv",
                    )
                    session.add(source)
                    session.flush()

                source.content_hash = row_hash(row)
                source.fetched_at = utcnow()
                source.status = 200
                source.identity_verified = True
                source.rejection_reason = None

                # Keep the complete original row in the source body. Every
                # imported fact can therefore be audited against the exact
                # registry record from which it was created.
                import json
                source.body = json.dumps(
                    {k: clean(v) for k, v in row.items()},
                    ensure_ascii=False,
                    sort_keys=True,
                )

                session.flush()

                # -------------------------------------------------
                # Facts
                # -------------------------------------------------

                for fact_key, column in FACT_COLUMNS.items():
                    raw_value = clean(row.get(column))
                    if raw_value is None:
                        continue

                    value_num, value_int = value_for_fact(fact_key, raw_value)
                    employee_as_of = (
                        clean(row.get("registreringsdatoAntallAnsatteEnhetsregisteret"))
                        if fact_key == "employees" else None
                    )
                    created = upsert_registry_fact(
                        session=session,
                        company=company,
                        source=source,
                        key=fact_key,
                        raw_value=raw_value,
                        column=column,
                        value_num=value_num,
                        value_int=value_int,
                        as_of=employee_as_of,
                    )
                    if created:
                        facts_created += 1

                # Deterministic status from the same Brreg row.
                konkurs = clean(row.get("konkurs"))
                under_avvikling = clean(row.get("underAvvikling"))
                under_tvang = clean(row.get("underTvangsavviklingEllerTvangsopplosning"))
                def true_flag(value: str | None) -> bool:
                    return str(value or "").strip().lower() in {"true", "1", "yes", "ja"}

                if true_flag(konkurs):
                    status_value = "bankrupt"
                elif true_flag(under_avvikling):
                    status_value = "under_liquidation"
                elif true_flag(under_tvang):
                    status_value = "under_forced_dissolution"
                else:
                    status_value = "active"

                status_created = upsert_registry_fact(
                    session=session,
                    company=company,
                    source=source,
                    key="company_status",
                    raw_value=status_value,
                    column="konkurs/underAvvikling/underTvangsavviklingEllerTvangsopplosning",
                )
                if status_created:
                    facts_created += 1

                session.flush()

            except Exception as e:
                errors += 1
                print(f"\n[PHASE 8 ERROR] orgnr={orgnr}: {type(e).__name__}: {e}")
                session.rollback()
                continue

    session.commit()

    return {
        "target_orgnrs": len(target_orgnrs),
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "facts_created": facts_created,
    }
