from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8801
    admin_secret: str = "change-me-admin-secret"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    small_model: str = "gpt-4o-mini"
    large_model: str = "gpt-4o"
    mock_llm: bool = True

    redis_url: str = "redis://localhost:6379/0"
    cache_similarity_high: float = 0.95
    cache_similarity_low: float = 0.80
    cache_default_ttl_seconds: int = 86400
    embedding_model: str = "all-MiniLM-L6-v2"

    typesafe_api_key: str = ""
    typesafe_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"
    jev_enabled: bool = True
    jev_confidence_threshold: float = 0.85
    mock_jev: bool = True

    default_rate_limit_per_hour: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
