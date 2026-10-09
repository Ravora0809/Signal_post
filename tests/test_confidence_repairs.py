import pytest

from signalpost.phases.p4_fact_extraction import extract_from_source


class FakeLLM:
    def __init__(self, facts):
        self.facts = facts

    async def extract_facts(self, body, allowed_keys):
        return self.facts, 0.0


class SourceStub:
    def __init__(self, *, url, kind, body):
        self.url = url
        self.kind = kind
        self.body = body
        self.identity_verified = True


@pytest.mark.asyncio
async def test_zero_confidence_ceo_and_chair_are_repaired_only_with_exact_verified_role_evidence():
    body = '{"rolle":"daglig leder","navn":"Example CEO"} {"rolle":"styrets leder","navn":"Example Chair"}'
    source = SourceStub(
        url="https://data.brreg.no/enhetsregisteret/api/enheter/123456789/roller",
        kind="brreg",
        body=body,
    )
    llm = FakeLLM([
        {"key": "ceo", "value": "Example CEO", "confidence": 0.0, "evidence": '"navn":"Example CEO"'},
        {"key": "chair", "value": "Example Chair", "confidence": 0.0, "evidence": '"navn":"Example Chair"'},
    ])

    facts, _ = await extract_from_source(llm, source)
    by_key = {fact["key"]: fact for fact in facts}
    assert by_key["ceo"]["confidence"] == 0.90
    assert by_key["chair"]["confidence"] == 0.90


@pytest.mark.asyncio
async def test_zero_confidence_website_is_repaired_only_when_official_host_matches():
    body = '<meta property="og:url" content="https://www.yara.com/" />'
    source = SourceStub(url="https://www.yara.com", kind="website", body=body)
    llm = FakeLLM([{
        "key": "website", "value": "https://www.yara.com/", "confidence": 0.0,
        "evidence": body,
    }])

    facts, _ = await extract_from_source(llm, source)
    website = next(fact for fact in facts if fact["key"] == "website")
    assert website["confidence"] == 0.90


@pytest.mark.asyncio
async def test_unverified_or_unmatched_zero_confidence_fact_is_not_inflated():
    body = '<meta property="og:url" content="https://wrong.example/" />'
    source = SourceStub(url="https://www.yara.com", kind="website", body=body)
    source.identity_verified = False
    llm = FakeLLM([{
        "key": "website", "value": "https://wrong.example/", "confidence": 0.0,
        "evidence": body,
    }])

    facts, _ = await extract_from_source(llm, source)
    # Unverified sources are rejected before extraction, so no claim is emitted.
    assert facts == []
