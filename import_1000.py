
from signalpost.db import get_session_factory
from signalpost.phases.p8_registry_import import import_registry_csv


CSV_PATH = "data/brreg_1000.csv"
ORGNR_PATH = "data/company_numbers_1000.txt"


def main():
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        result = import_registry_csv(
            session=session,
            csv_path=CSV_PATH,
            orgnr_path=ORGNR_PATH,
        )

        print("\n=== SIGNALPOST PHASE 8 ===")
        for key, value in result.items():
            print(f"{key}: {value}")

    finally:
        session.close()


if __name__ == "__main__":
    main()
