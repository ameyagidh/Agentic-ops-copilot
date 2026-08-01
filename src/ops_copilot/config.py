"""Central configuration. Every setting has a working default so the whole
system runs with zero environment variables (LLM provider ``fake``, backends
``mock``) — deploy it, then override via env vars or a ``.env`` file to point
at real systems.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["fake", "openai", "bedrock"]
LogsBackendName = Literal["mock", "loki"]
MetricsBackendName = Literal["mock", "prometheus"]


class Settings(BaseSettings):
    """All configuration, sourced from env vars prefixed ``OPS_`` or a
    ``.env`` file. See ``.env.example`` for the full list with comments.
    """

    model_config = SettingsConfigDict(
        env_prefix="OPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM provider ---
    llm_provider: LLMProvider = "fake"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    bedrock_region: str = "us-east-1"
    openai_api_key: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # --- Backends ---
    logs_backend: LogsBackendName = "mock"
    metrics_backend: MetricsBackendName = "mock"
    loki_base_url: str = "http://localhost:3100"
    prometheus_base_url: str = "http://localhost:9090"
    backend_timeout_seconds: float = 10.0

    # --- Retrieval ---
    retrieval_enabled: bool = True
    embeddings_provider: Literal["openai", "none"] = "none"
    runbooks_dir: str = "runbooks"
    vector_store_dir: str = ".chroma"

    # --- Persistence ---
    checkpoint_db_path: str = "data/checkpoints.sqlite"

    # --- API ---
    api_key: str | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    rate_limit_per_minute: int = 60

    # --- Observability ---
    log_level: str = "INFO"
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Use ``get_settings.cache_clear()`` in tests
    that mutate the environment.
    """
    return Settings()
