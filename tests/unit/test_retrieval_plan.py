"""Unit tests for RetrievalPlan / RoutingDecision (application-owned strategy).

Ensures the plan is vendor-free: no LightRAG / QueryParam / mode leakage,
and that every application strategy maps to a real intents/strategy value.
"""

from __future__ import annotations

from polaris_agentic_rag.retrieval.models import (
    RetrievalIntent,
    RetrievalPlan,
    RetrievalStrategy,
    RoutingDecision,
)


def test_default_plan_fields() -> None:
    plan = RetrievalPlan(
        intent=RetrievalIntent.FACTUAL,
        strategy=RetrievalStrategy.FOCUSED,
        top_k=20,
    )
    assert plan.intent is RetrievalIntent.FACTUAL
    assert plan.strategy is RetrievalStrategy.FOCUSED
    assert plan.top_k == 20
    assert plan.chunk_top_k is None
    assert plan.enable_rerank is False
    assert plan.reason == ""


def test_plan_has_no_vendor_fields() -> None:
    plan = RetrievalPlan(
        intent=RetrievalIntent.GENERAL,
        strategy=RetrievalStrategy.HYBRID,
        top_k=20,
    )
    raw = plan.model_dump()
    for banned in ("mode", "QueryParam", "LightRAG"):
        assert banned not in raw, f"vendor field leaked: {banned}"
    #: strategy is application-owned, not a LightRAG mode string
    assert set(RetrievalPlan.model_fields) == {
        "intent",
        "strategy",
        "top_k",
        "chunk_top_k",
        "enable_rerank",
        "reason",
    }


def test_all_strategies_are_application_owned() -> None:
    expected = {"focused", "global", "hybrid", "vector", "mixed"}
    assert {s.value for s in RetrievalStrategy} == expected


def test_all_intents_are_bounded() -> None:
    expected = {"factual", "terminology", "relational", "multi_document", "overview", "general"}
    assert {i.value for i in RetrievalIntent} == expected


def test_routing_decision_is_observable() -> None:
    decision = RoutingDecision(
        intent=RetrievalIntent.MULTI_DOCUMENT,
        strategy=RetrievalStrategy.HYBRID,
        reason="operational multi-step task",
        fallback_used=False,
    )
    assert decision.fallback_used is False
    assert decision.intent.value == "multi_document"


def test_routing_decision_tracks_fallback() -> None:
    decision = RoutingDecision(
        intent=RetrievalIntent.GENERAL,
        strategy=RetrievalStrategy.HYBRID,
        reason="router raised while routing",
        fallback_used=True,
    )
    assert decision.fallback_used is True
