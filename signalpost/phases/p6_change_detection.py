from sqlalchemy.orm import Session
from sqlalchemy import desc
from ..models import Fact, FactHistory


def fact_value(fact: Fact) -> str:
    """Canonical scalar representation across text/int/float fact columns."""
    if fact.value_int is not None:
        return str(int(fact.value_int))
    if fact.value_num is not None:
        value = float(fact.value_num)
        return str(int(value)) if value.is_integer() else format(value, ".15g")
    return (fact.value_text or "").strip()


def snapshot_previous(session: Session, company_id: int) -> dict[str, Fact]:
    """Capture the latest verified state before the new observation batch."""
    rows = (
        session.query(Fact)
        .filter(Fact.company_id == company_id, Fact.verified.is_(True))
        .order_by(desc(Fact.observed_at), desc(Fact.id))
        .all()
    )
    previous: dict[str, Fact] = {}
    for row in rows:
        previous.setdefault(row.key, row)
    return previous


def detect_changes(
    session: Session,
    company_id: int,
    previous: dict[str, Fact],
    new_facts: list[Fact],
) -> list[FactHistory]:
    """Append history only for verified values observed in this run.

    Missing extraction output is not evidence that a value was removed. This
    function records additions and changes from verified facts; a removal must
    be represented by an explicit authoritative tombstone in a future adapter.
    """
    current: dict[str, Fact] = {}
    for fact in sorted(
        new_facts,
        key=lambda item: (item.observed_at, item.id or 0),
        reverse=True,
    ):
        if fact.verified:
            current.setdefault(fact.key, fact)

    changes: list[FactHistory] = []
    for key, cur in current.items():
        new_value = fact_value(cur)
        prev = previous.get(key)
        if prev is None:
            changes.append(
                FactHistory(
                    company_id=company_id,
                    key=key,
                    old_value=None,
                    new_value=new_value,
                    change_type="added",
                )
            )
            continue

        old_value = fact_value(prev)
        if old_value != new_value:
            changes.append(
                FactHistory(
                    company_id=company_id,
                    key=key,
                    old_value=old_value,
                    new_value=new_value,
                    change_type="changed",
                )
            )

    if changes:
        session.add_all(changes)
        session.flush()
    return changes
