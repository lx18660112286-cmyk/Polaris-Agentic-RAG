"""QueryRouter -- deterministic, fallback-safe retrieval routing.

Stage 3 uses a deterministic rule router on purpose (no LLM classifier):
it is cheap, offline-testable, and gives a stable routing baseline so a
future LLM router can be judged on merit, not randomness.

The Router is part of the application strategy layer. It must never
import LightRAG / adapters / tools / agent (enforced by the architecture
guard). Fallback is explicit and observable, never silent.
"""

from __future__ import annotations

from polaris_agentic_rag.retrieval.models import (
    RetrievalIntent,
    RetrievalPlan,
    RoutingDecision,
)
from polaris_agentic_rag.retrieval.rules import (
    decide_intent,
    default_plan_for_intent,
    extract_features,
)

__all__ = ["QueryRouter"]

_FALLBACK_REASON = "router raised while routing -> safe hybrid fallback plan"


class QueryRouter:
    """Route a user query to an application-owned RetrievalPlan."""

    def __init__(self, *, default_top_k: int = 20, enable_rerank: bool = False) -> None:
        self._default_top_k = default_top_k
        self._enable_rerank = enable_rerank

    def route(self, query: str) -> RetrievalPlan:
        """Return the RetrievalPlan for ``query`` (deterministic; no I/O).

        On an unexpected failure we fall back to a safe hybrid plan and
        surface ``fallback_used`` via :meth:`last_decision` rather than
        raising or silently guessing.
        """
        try:
            features = extract_features(query)
            intent = decide_intent(features, query)
            plan = default_plan_for_intent(
                intent,
                top_k=self._default_top_k,
                enable_rerank=self._enable_rerank,
            )
            self._last_decision = RoutingDecision(
                intent=intent,
                strategy=plan.strategy,
                reason=plan.reason,
                fallback_used=False,
            )
            return plan
        except Exception:  # noqa: BLE001 - routing must never break the Tool
            plan = default_plan_for_intent(
                RetrievalIntent.GENERAL,
                top_k=self._default_top_k,
                enable_rerank=self._enable_rerank,
            )
            self._last_decision = RoutingDecision(
                intent=plan.intent,
                strategy=plan.strategy,
                reason=_FALLBACK_REASON,
                fallback_used=True,
            )
            return plan

    @property
    def last_decision(self) -> RoutingDecision | None:
        """The most recent routing decision (for observability/tests)."""
        return getattr(self, "_last_decision", None)
