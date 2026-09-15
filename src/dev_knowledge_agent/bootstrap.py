"""Composition root (Stage 2 -> Stage 3).

This is the only application-level place allowed to know the concrete
``LightRAGAdapter`` that satisfies ``KnowledgeSearchPort``. It wires:

    settings -> LightRAGAdapter -> QueryRouter -> RagSearchTool

It does NOT import LightRAG directly -- only ``LightRAGAdapter``,
``QueryRouter`` and ``RagSearchTool``. No Agent is created (Stage 4).
"""

from __future__ import annotations

from pathlib import Path

from dev_knowledge_agent.adapters.lightrag.adapter import LightRAGAdapter
from dev_knowledge_agent.adapters.lightrag.settings import (
    LightRAGAdapterSettings,
    get_lightrag_adapter_settings,
)
from dev_knowledge_agent.retrieval.router import QueryRouter
from dev_knowledge_agent.tools.rag_search import RagSearchTool

__all__ = ["build_rag_search_tool", "create_lightrag_adapter"]


def create_lightrag_adapter(
    settings: LightRAGAdapterSettings | None = None,
    working_dir: str | Path | None = None,
    knowledge_roots: list[Path] | None = None,
) -> LightRAGAdapter:
    """Build a LightRAGAdapter from settings (only used by the composition root)."""
    return LightRAGAdapter(
        working_dir=working_dir,
        settings=settings or get_lightrag_adapter_settings(),
        knowledge_roots=knowledge_roots,
    )


def build_rag_search_tool(*, adapter: LightRAGAdapter) -> RagSearchTool:
    """Bind the concrete adapter to a RagSearchTool via the Port + Router."""
    return RagSearchTool(search_port=adapter, router=QueryRouter())
