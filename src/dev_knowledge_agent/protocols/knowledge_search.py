"""KnowledgeSearchPort -- the framework-agnostic domain protocol.

The Port is intentionally tiny for Stage 2: it accepts only the query
string and returns a domain ``KnowledgeSearchResult``. It does NOT
expose vendor-specific types (``QueryParam``, ``LightRAG``, ``mode``,
``enable_rerank``) or a ``RetrievalPlan`` (which is Stage 3).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from dev_knowledge_agent.evidence.models import KnowledgeSearchResult

__all__ = ["KnowledgeSearchPort"]


@runtime_checkable
class KnowledgeSearchPort(Protocol):
    """Abstract knowledge retrieval capability for the agent layer."""

    async def search(self, query: str) -> KnowledgeSearchResult:
        """Search the developer knowledge base for ``query``.

        Raises domain errors (see ``dev_knowledge_agent.evidence.errors``)
        on failure; never leaks vendor-specific exceptions.
        """
        ...
