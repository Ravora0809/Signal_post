"""Phase 2: database helpers and schema health checks."""
from sqlalchemy import text
from sqlalchemy.orm import Session


def database_health(session: Session) -> dict:
    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "postgresql"}


def counts(session: Session) -> dict:
    from ..models import Company, Source, Fact
    return {
        "companies": session.query(Company).count(),
        "sources": session.query(Source).count(),
        "facts": session.query(Fact).count(),
    }
