from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://signalpost:signalpost@localhost:5432/signalpost"
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None
    llm_provider: str = "openrouter"
    llm_model: str = "openai/gpt-4o-mini"
    brave_api_key: str | None = None
    search_provider: str = "duckduckgo"
    max_requests: int = 2000
    max_runtime_seconds: int = 2700
    max_cost_usd: float = 10.0
    http_timeout: float = 15.0
    http_concurrency: int = 12
    http_cache_ttl_seconds: int = 300
    user_agent: str = "SignalPostBot/1.0 (+public-company-research)"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
