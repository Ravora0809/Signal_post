from __future__ import annotations

from collections import defaultdict

from signalpost.db import get_session_factory
from signalpost.models import Fact, FactHistory, Source
from signalpost.phases.p8_registry_import import canonical_fact_value


def main() -> None:
    SessionLocal = get_session_factory()
    session = SessionLocal()
    renamed_facts = 0
    renamed_history = 0
    reclassified = 0
    try:
        facts = session.query(Fact).filter(Fact.key == "debt").order_by(Fact.id).all()
        by_company = defaultdict(list)
        for fact in facts:
            by_company[fact.company_id].append(fact)

        for company_id, legacy_facts in by_company.items():
            current_liabilities = session.query(Fact).filter(
                Fact.company_id == company_id,
                Fact.key == "total_liabilities",
                Fact.verified.is_(True),
            ).count()
            for fact in legacy_facts:
                # If a current canonical fact already exists, keep the legacy
                # row for audit but retire it from published current facts.
                if current_liabilities and fact.verified:
                    fact.verified = False
                fact.key = "total_liabilities"
                renamed_facts += 1

        renamed_history = session.query(FactHistory).filter(
            FactHistory.key == "debt"
        ).update({"key": "total_liabilities"}, synchronize_session=False)

        # If an old 'changed' event joins facts from different source kinds, it
        # was a source/schema reconciliation, not a proven company change.
        events = session.query(FactHistory).filter(
            FactHistory.change_type == "changed"
        ).all()
        for event in events:
            if event.old_value is None or event.new_value is None:
                continue
            candidates = session.query(Fact).filter(
                Fact.company_id == event.company_id, Fact.key == event.key
            ).all()
            old_fact = next((f for f in candidates if canonical_fact_value(f) == event.old_value), None)
            new_fact = next((f for f in candidates if canonical_fact_value(f) == event.new_value), None)
            if not old_fact or not new_fact or not old_fact.source_id or not new_fact.source_id:
                continue
            old_source = session.query(Source).filter_by(id=old_fact.source_id, company_id=event.company_id).one_or_none()
            new_source = session.query(Source).filter_by(id=new_fact.source_id, company_id=event.company_id).one_or_none()
            if old_source and new_source and old_source.kind != new_source.kind:
                event.change_type = "reconciled"
                reclassified += 1

        session.commit()
        print("Signalpost history/schema migration complete")
        print(f"Fact keys renamed debt -> total_liabilities: {renamed_facts}")
        print(f"History keys renamed debt -> total_liabilities: {renamed_history}")
        print(f"Cross-source history events reclassified as reconciled: {reclassified}")
        print("Values were preserved; reconciled events are not counted as confirmed changes.")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
