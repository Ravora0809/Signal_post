import pytest
from unittest.mock import AsyncMock, patch
from signalpost.pipeline import SignalPostPipeline
from signalpost.models import Company


@pytest.mark.asyncio
async def test_pipeline_not_found(monkeypatch):
    pipeline = SignalPostPipeline()

    async def fake_run(session, http, orgnr):
        return None

    monkeypatch.setattr("signalpost.pipeline.p1_company_lookup.run", fake_run)
    _, result = None, await pipeline.research_one(type("S", (), {"add": lambda *a: None, "flush": lambda *a: None, "query": lambda *a: None})(), "923609016")
    assert result["status"] == "not_found"
    await pipeline.aclose()