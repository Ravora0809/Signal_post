from sqlalchemy.orm import Session
from sqlalchemy import desc
from ..models import Fact, FactHistory


def snapshot_previous(session: Session, company_id: int) -> dict[str, Fact]:
    """Capture the latest verified state BEFORE creating the new observation batch."""
    rows = session.query(Fact).filter(Fact.company_id == company_id, Fact.verified.is_(True)).order_by(desc(Fact.observed_at), desc(Fact.id)).all()
    previous = {}
    for row in rows:
        previous.setdefault(row.key, row)
    return previous


def detect_changes(session: Session, company_id: int, previous: dict[str, Fact], new_facts: list[Fact]) -> list[FactHistory]:
    current: dict[str, Fact] = {}
    conflicted_keys = {f.key for f in new_facts if f.conflict}
    for f in sorted(new_facts, key=lambda x: (x.observed_at, x.id or 0), reverse=True):
        if f.verified and f.key not in current:
            current[f.key] = f
    changes: list[FactHistory] = []
    for key, cur in current.items():
        prev = previous.get(key)
        if prev is None:
            changes.append(FactHistory(company_id=company_id, key=key, old_value=None, new_value=cur.value_text, change_type="added"))
        elif (prev.value_text or "").strip().casefold() != (cur.value_text or "").strip().casefold():
            changes.append(FactHistory(company_id=company_id, key=key, old_value=prev.value_text, new_value=cur.value_text, change_type="changed"))
    # A missing extraction is not automatically a removal: it may be an extraction failure.
    # Only explicit conflict-free observations can participate in a removal decision.
    observed_keys = {f.key for f in new_facts}
    for key, prev in previous.items():
        if key not in current and key in observed_keys and key not in conflicted_keys:
            prev.verified = False
            changes.append(FactHistory(company_id=company_id, key=key, old_value=prev.value_text, new_value=None, change_type="removed"))
    session.add_all(changes)
    session.flush()
    return changes
