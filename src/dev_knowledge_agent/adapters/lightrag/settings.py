"""LightRAG adapter settings.

These fields are used in Stage 0 for source understanding and future
adapter preparation. No real query is executed in Stage 0.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class LightRAGAdapterSettings(BaseSettings):
    """Settings describing how the LightRAG kernel adapter is configured."""

    model_config = SettingsConfigDict(
        env_prefix="DKA_LIGHTRAG_",
        env_file=".env",
        extra="ignore",
    )

    #: Directory used by LightRAG for storage / index data.
    working_dir: Path = Path("storage/lightrag")

    #: Source checkout location of the LightRAG kernel.
    source_dir: Path = Path("third_party/LightRAG")

    #: Storage namespace. LightRAG scopes its doc_status dedup and stores by
    #: ``workspace``; an empty value shares the global ``WORKSPACE`` env /
    #: default. Set a unique value to isolate one knowledge base from another.
    workspace: str = ""

    #: Default query mode forwarded to the kernel (local / global /
    #: hybrid / mix). Reserved for the future adapter, not used in Stage 0.
    default_query_mode: str = "hybrid"

    default_top_k: int = 20

    enable_rerank: bool = False

    include_references: bool = True


def get_lightrag_adapter_settings() -> LightRAGAdapterSettings:
    """Return a cached LightRAG adapter settings instance."""
    return LightRAGAdapterSettings()
