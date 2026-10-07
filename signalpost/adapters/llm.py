import json
import structlog
from ..config import get_settings

log = structlog.get_logger()


class LLMAdapter:
    """OpenRouter/OpenAI-compatible structured fact extraction adapter."""

    def __init__(self):
        s = get_settings()
        self.provider = s.llm_provider.lower()
        self.model = s.llm_model
        self.api_key = s.openrouter_api_key if self.provider == "openrouter" else s.openai_api_key
        self.base_url = "https://openrouter.ai/api/v1" if self.provider == "openrouter" else None
        self.enabled = bool(self.api_key)
        self._client = None
        if self.enabled:
            from openai import AsyncOpenAI
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
                kwargs["default_headers"] = {"HTTP-Referer": "https://signalpost.local", "X-Title": "Signalpost"}
            self._client = AsyncOpenAI(**kwargs)

    async def extract_facts(self, text: str, schema_keys: list[str]) -> tuple[list[dict], float]:
        if not self.enabled:
            return [], 0.0
        prompt = (
            "Extract only facts explicitly supported by the supplied company source. "
            "Never infer, guess, or use outside knowledge. For every fact return an exact "
            "evidence quote copied from the source. Allowed keys: " + ", ".join(schema_keys) +
            '. Return ONLY JSON: {"facts":[{"key":"...","value":...,"confidence":0.0,"evidence":"..."}]}.'
            "\nSOURCE:\n" + text[:18000]
        )
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a strict company-fact extraction engine."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            facts = data.get("facts", []) or []
            usage = getattr(resp, "usage", None)
            # Conservative estimate. Exact provider pricing can vary by model.
            cost = 0.0
            if usage:
                input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(usage, "completion_tokens", 0) or 0
                cost = (input_tokens + output_tokens) * 0.000001
            return facts, cost
        except Exception as exc:
            log.warning("llm_extract_failed", provider=self.provider, model=self.model, error=str(exc))
            return [], 0.0
