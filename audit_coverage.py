from collections import Counter
from signalpost.db import session_scope
from signalpost.models import Company, Fact

USEFUL_KEYS = {
    "employees": 4,
    "industry": 4,
    "address": 4,
    "city": 2,
    "postal_code": 1,
    "legal_form": 2,
    "phone": 1,
    "email": 1,
    "website": 1,
    "founded_year": 2,
    "registration_date": 2,
    "industry_code": 2,
    "revenue_nok": 3,
    "profit_nok": 3,
    "capital_nok": 3,
}

with session_scope() as session:
    companies = session.query(Company).all()

    total = len(companies)

    counts = Counter()

    for company in companies:
        facts = (
            session.query(Fact)
            .filter(
                Fact.company_id == company.id,
                Fact.verified.is_(True),
            )
            .all()
        )

        keys = {f.key for f in facts}

        for key in USEFUL_KEYS:
            # Revenue/profit: accept either NOK or generic currency form.
            if key == "revenue_nok":
                if "revenue_nok" in keys or "revenue" in keys:
                    counts[key] += 1
            elif key == "profit_nok":
                if "profit_nok" in keys or "profit" in keys:
                    counts[key] += 1
            elif key in keys:
                counts[key] += 1

    print("\nSIGNALPOST COVERAGE AUDIT")
    print("=" * 60)

    total_points = 0

    for key, weight in USEFUL_KEYS.items():
        count = counts[key]
        pct = (count / total * 100) if total else 0
        contribution = (count / total * weight) if total else 0
        total_points += contribution

        print(
            f"{key:20} "
            f"{count:4}/{total} "
            f"{pct:6.1f}% "
            f"avg points: {contribution:5.2f}"
        )

    print("=" * 60)
    print(f"Estimated coverage: {total_points:.2f}/35")