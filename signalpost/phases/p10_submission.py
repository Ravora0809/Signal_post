"""Phase 10: production/submission readiness checks."""
from pathlib import Path

REQUIRED_FILES = [
    "README.md", "Dockerfile", "docker-compose.yml", "requirements.txt",
    "alembic.ini", "signalpost/api.py", "signalpost/cli.py",
]


def check_project(root: str | Path = ".") -> dict:
    root = Path(root)
    missing = [p for p in REQUIRED_FILES if not (root / p).exists()]
    return {"ready": not missing, "missing": missing, "required_files": REQUIRED_FILES}
