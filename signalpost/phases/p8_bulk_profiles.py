import asyncio
import csv
import structlog
from pathlib import Path
from ..models import Company

log = structlog.get_logger()


def load_orgnrs(path: str | Path) -> list[str]:
    p = Path(path)
    values = []
    if p.suffix.lower() == ".csv":
        with p.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames and "orgnr" in {x.lower() for x in reader.fieldnames}:
                field = next(x for x in reader.fieldnames if x.lower() == "orgnr")
                values = [(row.get(field) or "").strip() for row in reader]
            else:
                fh.seek(0)
                values = [line.strip().split(",")[0] for line in fh]
    else:
        values = [line.strip() for line in p.read_text(encoding="utf-8").splitlines()]
    seen, out = set(), []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


async def run_bulk(session_factory, pipeline, orgnrs: list[str], concurrency: int = 4, retries: int = 2) -> dict:
    sem = asyncio.Semaphore(max(1, concurrency))
    results = {"ok": 0, "not_found": 0, "fail": 0, "retried": 0, "failed_orgnrs": []}
    lock = asyncio.Lock()

    async def worker(orgnr: str):
        attempt = 0
        while attempt <= retries:
            async with sem:
                session = session_factory()
                try:
                    result = await pipeline.research_one(session, orgnr)
                    session.commit()
                except Exception as e:
                    session.rollback()
                    result = {"status": "error", "error": str(e)}
                finally:
                    session.close()
            if result.get("status") == "ok":
                async with lock: results["ok"] += 1
                return
            if result.get("status") == "not_found":
                async with lock: results["not_found"] += 1
                return
            attempt += 1
            if attempt <= retries:
                async with lock: results["retried"] += 1
                await asyncio.sleep(min(2 ** attempt, 30))
            else:
                async with lock:
                    results["fail"] += 1
                    results["failed_orgnrs"].append(orgnr)
                return

    await asyncio.gather(*(worker(o) for o in orgnrs))
    return results
