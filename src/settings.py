"""Centralised, type-checked configuration.

Loads from environment / `.env` once at import time and surfaces a clear
ValidationError if required keys are missing. Optional keys remain `None`.

Every env variable referenced anywhere in the codebase should be declared
here so `.env.example` is the single source of truth.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Required ─────────────────────────────────────────────────────────
    anthropic_api_key: SecretStr = Field(description="https://console.anthropic.com/settings/keys")

    # ── Models ───────────────────────────────────────────────────────────
    model_haiku: str = "claude-haiku-4-5-20251001"
    model_sonnet: str = "claude-sonnet-4-6"
    model_opus: str = "claude-opus-4-7"

    # ── Default execution mode ───────────────────────────────────────────
    default_mode: str = "auto"

    # ── Crew configuration ───────────────────────────────────────────────
    crew_memory: bool = False
    llm_timeout_seconds: float = 300.0
    crew_embedder_provider: str = "local"

    # ── Search providers (any of these enables a live provider) ─────────
    tavily_api_key: SecretStr | None = None
    serper_api_key: SecretStr | None = None
    adzuna_app_id: SecretStr | None = None
    adzuna_app_key: SecretStr | None = None
    rapidapi_key: SecretStr | None = None
    apify_token: SecretStr | None = None

    # ── Embeddings backend for the search reranker ──────────────────────
    # 'local' | 'voyage' | 'openai'
    embeddings_provider: str = "local"
    voyage_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # ── Spend cap (informational; enforced by main.py) ──────────────────
    spend_limit_usd: float | None = None

    # ── Observability ────────────────────────────────────────────────────
    log_level: str = "INFO"
    crewai_tracing: bool = False
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # ── Helpers ──────────────────────────────────────────────────────────
    def reveal(self, key: SecretStr | None) -> str | None:
        return key.get_secret_value() if key else None


_settings: Settings | None = None


def get_settings() -> Settings:
    """Lazy singleton — first call validates env, subsequent calls are free."""
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
