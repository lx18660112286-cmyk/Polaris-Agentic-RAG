"""Retrieval routing domain model (application-owned).

These types are OUR domain types -- they are framework-agnostic and
carry no LightRAG / ``QueryParam`` types. ``RetrievalStrategy`` is the
application's own language for "how to retrieve"; the mapping to a real
LightRAG ``mode`` lives only inside ``adapters/lightrag/``.

Spec (§3-7): the Agent/Caller only ever provides ``query``; the Router
turns it into a ``RetrievalPlan`` that the ``KnowledgeSearchPort`` +
adapter obey. The Agent never controls ``mode/top_k/rerank``.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

__all__ = [
    "RetrievalStrategy",
    "RetrievalIntent",
    "RetrievalPlan",
    "RoutingDecision",
]


class RetrievalStrategy(str, Enum):
    """Application-owned retrieval strategy (NOT a LightRAG mode).

    Semantics (grounded in Stage 1 observations):

    * FOCUSED -- precise entity / exact fact / local knowledge
    * GLOBAL   -- system overview / high-level relationship / whole-system
    * HYBRID   -- graph structure + chunk combined retrieval
    * VECTOR   -- pure semantic vector retrieval (naive)
    * MIXED    -- graph + vector joint path
    """

    FOCUSED = "focused"
    GLOBAL = "global"
    HYBRID = "hybrid"
    VECTOR = "vector"
    MIXED = "mixed"


class RetrievalIntent(str, Enum):
    """Why the user is asking (small, deterministic, explainable set)."""

    FACTUAL = "factual"
    TERMINOLOGY = "terminology"
    RELATIONAL = "relational"
    MULTI_DOCUMENT = "multi_document"
    OVERVIEW = "overview"
    GENERAL = "general"


class RetrievalPlan(BaseModel):
    """Concrete retrieval parameters decided by the Router.

    Deliberately vendor-free: no ``QueryParam``, no LightRAG ``mode``.
    The adapter translates ``strategy`` into a real kernel mode.
    """

    intent: RetrievalIntent
    strategy: RetrievalStrategy
    top_k: int
    chunk_top_k: int | None = None
    enable_rerank: bool = False
    reason: str = ""


class RoutingDecision(BaseModel):
    """Why the Router chose a plan. For debugging / tests / observability.

    The Agent does NOT decide this; it is surfaced so a caller can
    inspect the intent & strategy and observe fallback usage.
    """

    intent: RetrievalIntent
    strategy: RetrievalStrategy
    reason: str = ""
    fallback_used: bool = False
