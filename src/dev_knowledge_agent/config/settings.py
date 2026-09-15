"""Application-level settings for Dev Knowledge Agent.

These settings describe the application and its relationship to the
LightRAG kernel. They deliberately do NOT configure LightRAG-specific
query details (mode, top_k, rerank ...) — those live in the adapter
settings (``dev_knowledge_agent.adapters.lightrag.settings``).
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_prefix="DKA_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "dev-knowledge-agent"

    environment: str = "development"

    log_level: str = "INFO"

    #: Working directory for LightRAG storage / index data.
    lightrag_working_dir: Path = Path("storage/lightrag")

    #: Absolute path to the LightRAG source checkout (git submodule).
    lightrag_source_dir: Path = Path("third_party/LightRAG")

    #: How LightRAG is integrated. Stage 0 pins "source_sdk".
    lightrag_integration_mode: str = "source_sdk"


def get_settings() -> Settings:
    """Return a cached application settings instance."""
    return Settings()
