import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Company, Source, Fact


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

                # Keep the actual row available as evidence.
                source.body = (
                    f"organisasjonsnummer={orgnr}\n"
                    f"navn={name}\n"
                    f"row_hash={row_hash(row)}"
                )

                session.flush()

                # -------------------------------------------------
                # Facts
                # -------------------------------------------------

                for fact_key, column in FACT_COLUMNS.items():

                    raw_value = clean(row.get(column))

                    if raw_value is None:
                        continue

                    value_num, value_int = value_for_fact(
                        fact_key,
                        raw_value,
                    )

                    existing = (
                        session.query(Fact)
                        .filter(
                            Fact.company_id == company.id,
                            Fact.key == fact_key,
                            Fact.source_id == source.id,
                            Fact.value_text == raw_value,
                        )
                        .first()
                    )

                    if existing:
                        continue

                    fact = Fact(
                        company_id=company.id,
                        key=fact_key,
                        value_text=raw_value,
                        value_num=value_num,
                        value_int=value_int,
                        source_id=source.id,
                        evidence_snippet=evidence(
                            column,
                            raw_value,
                        ),
                        confidence=1.0,
                        verified=True,
                        conflict=False,
                        observed_at=utcnow(),
                    )

                    session.add(fact)
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
