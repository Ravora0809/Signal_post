import time
import structlog
from sqlalchemy.orm import Session
from .adapters.http import SafeHTTPClient
from .adapters.llm import LLMAdapter
from .adapters.search import SearchAdapter
from .config import get_settings
from .models import RunLog, Fact, Source
from .utils.rate_limit import Budget
from .phases import p1_company_lookup, p3_source_collection, p4_fact_extraction, p5_fact_validation, p6_change_detection

log = structlog.get_logger()


class SignalPostPipeline:
    def __init__(self):
        s = get_settings()
        self.budget = Budget(s.max_requests, s.max_runtime_seconds, s.max_cost_usd, s.max_runtime_seconds)
        self.http = SafeHTTPClient(self.budget)
        self.llm = LLMAdapter()
        self.search = SearchAdapter(self.budget, self.http)

    async def aclose(self):
        await self.http.aclose()

    async def research_one(self, session: Session, orgnr: str) -> dict:
        t0, stage = time.monotonic(), "start"
        result = {"orgnr": orgnr, "status": "unknown"}
        try:
            stage = "p1_lookup"
            company = await p1_company_lookup.run(session, self.http, orgnr)
            if not company:
                result["status"] = "not_found"
                return self._log_run(session, stage, None, "skip", "invalid or unknown company", t0, result)

            # IMPORTANT: snapshot old state before writing any new facts.
            previous = p6_change_detection.snapshot_previous(session, company.id)

            stage = "p3_sources"
            sources = await p3_source_collection.collect(session, self.http, self.search, company)
            stage = "p4_extract"
            all_new_facts = []
            for src in sources:
                facts_data, cost = await p4_fact_extraction.extract_from_source(self.llm, src)
                if cost:
                    if not self.budget.can_spend(cost=cost):
                        raise RuntimeError("API cost budget exhausted")
                    self.budget.spend(cost=cost)
                if facts_data:
                    all_new_facts.extend(p4_fact_extraction.persist_facts(session, company, src, facts_data))

            stage = "p5_validate"
            p5_fact_validation.validate_and_publish(session, company.id, all_new_facts)
            stage = "p6_changes"
            changes = p6_change_detection.detect_changes(session, company.id, previous, all_new_facts)
            session.flush()
            verified_facts = session.query(Fact).filter(
                Fact.company_id == company.id, Fact.verified.is_(True)
            ).order_by(Fact.observed_at.desc(), Fact.id.desc()).all()
            latest = {}
            for f in verified_facts:
                latest.setdefault(f.key, f.value_text)
            employee_fact = next((f for f in verified_facts if f.key == "employees"), None)
            if employee_fact and employee_fact.source_id:
                employee_source = session.query(Source).filter_by(id=employee_fact.source_id).one_or_none()
                if employee_source and employee_source.kind == "brreg":
                    latest["employees_scope"] = "Registered entity count; not a group-wide workforce total."
            result.update({"status": "ok", "company_id": company.id, "company_name": company.name, "sources": len(sources), "facts_observed": len(all_new_facts), "verified_facts": sum(f.verified for f in all_new_facts), "changes": len(changes), "profile": latest, "accounting_checks": p5_fact_validation.accounting_consistency_check(verified_facts), "budget": self.budget.snapshot()})
            return self._log_run(session, stage, company.id, "ok", f"facts={len(all_new_facts)} changes={len(changes)}", t0, result)
        except Exception as e:
            log.exception("pipeline_error", orgnr=orgnr, stage=stage)
            result.update({"status": "error", "stage": stage, "error": str(e), "budget": self.budget.snapshot()})
            return self._log_run(session, stage, result.get("company_id"), "error", str(e), t0, result)

    def _log_run(self, session, phase, company_id, status, message, t0, result):
        duration_ms = int((time.monotonic() - t0) * 1000)
        session.add(RunLog(phase=phase, company_id=company_id, status=status, message=message,
                           requests_used=self.budget.requests, cost_usd=self.budget.cost_usd, duration_ms=duration_ms))
        result["duration_ms"] = duration_ms
        return result
