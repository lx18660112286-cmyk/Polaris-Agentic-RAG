"""KnowledgeSearchPort -- the framework-agnostic domain protocol.

The Port takes the query string and an optional application-owned
``RetrievalPlan`` (Stage 3) and returns a domain ``KnowledgeSearchResult``. It
does NOT expose vendor types (``QueryParam``, ``LightRAG``, ``mode``,
``enable_rerank``). ``plan=None`` lets the adapter use its default strategy
(e.g. non-routed callers), but the Tool's normal path always passes a
Router-generated plan.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from polaris_agentic_rag.evidence.models import KnowledgeSearchResult
from polaris_agentic_rag.retrieval.models import RetrievalPlan

__all__ = ["KnowledgeSearchPort"]


@runtime_checkable
class KnowledgeSearchPort(Protocol):
    """Abstract knowledge retrieval capability for the agent layer."""

    async def search(
        self,
        query: str,
        *,
        plan: RetrievalPlan | None = None,
    ) -> KnowledgeSearchResult:
        """Search the developer knowledge base for ``query``.

        ``plan`` is an application-owned retrieval plan (intent + strategy +
        retrieval limits). When ``None``, the implementation uses its default
        strategy.

        Raises domain errors (see ``polaris_agentic_rag.evidence.errors``)
        on failure; never leaks vendor-specific exceptions.
        """
        ...
