"""Retrieval routing layer (Stage 3).

Owns the application strategy: ``RetrievalStrategy`` / ``RetrievalIntent``
/ ``RetrievalPlan`` / ``RoutingDecision`` and the deterministic
``QueryRouter``. This layer is vendor-free -- it never imports LightRAG,
adapters, tools, or agent (enforced by the architecture guard).
"""

from __future__ import annotations

from polaris_agentic_rag.retrieval.models import (
    RetrievalIntent,
    RetrievalPlan,
    RetrievalStrategy,
    RoutingDecision,
)
from polaris_agentic_rag.retrieval.router import QueryRouter

__all__ = [
    "QueryRouter",
    "RetrievalIntent",
    "RetrievalPlan",
    "RetrievalStrategy",
    "RoutingDecision",
]
