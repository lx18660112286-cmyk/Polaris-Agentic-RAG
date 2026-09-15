"""Unit tests for QueryRouter (deterministic, offline, no LightRAG).

Covers the six required intents (spec §21), the explicit GENERAL fallback,
determinism, and the mapping used by the Tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from polaris_agentic_rag.retrieval.models import (
    RetrievalIntent,
    RetrievalPlan,
    RetrievalStrategy,
)
from polaris_agentic_rag.retrieval.router import QueryRouter

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "routing_cases.json").read_text(
        encoding="utf-8"
    )
)


def test_router_is_deterministic_across_calls() -> None:
    router = QueryRouter()
    for case in FIXTURES["cases"]:
        plan_a = router.route(case["query"])
        plan_b = router.route(case["query"])
        assert plan_a == plan_b, f"non-deterministic routing for {case['case_id']}"


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda c: c["case_id"])
def test_router_routes_each_required_case(case: dict) -> None:
    router = QueryRouter()
    plan = router.route(case["query"])
    assert plan.intent.value == case["expected_intent"], (
        f"{case['case_id']}: expected intent {case['expected_intent']}, got {plan.intent.value}"
    )
    assert plan.strategy.value == case["expected_strategy"], (
        f"{case['case_id']}: expected strategy {case['expected_strategy']}, "
        f"got {plan.strategy.value}"
    )
    #: routing decision matches the plan and is observable
    decision = router.last_decision
    assert decision is not None
    assert decision.intent == plan.intent
    assert decision.strategy == plan.strategy


def test_factual_routes_to_focused() -> None:
    plan = QueryRouter().route("Access token 的有效期是多少？")
    assert plan.intent is RetrievalIntent.FACTUAL
    assert plan.strategy is RetrievalStrategy.FOCUSED


def test_terminology_routes_to_focused() -> None:
    plan = QueryRouter().route("DB_CONNECTION_POOL_EXHAUSTED 是什么意思？")
    assert plan.intent is RetrievalIntent.TERMINOLOGY
    assert plan.strategy is RetrievalStrategy.FOCUSED


def test_relational_routes_to_hybrid() -> None:
    plan = QueryRouter().route("Order Service 依赖哪些组件？")
    assert plan.intent is RetrievalIntent.RELATIONAL
    assert plan.strategy is RetrievalStrategy.HYBRID


def test_multi_document_routes_to_hybrid() -> None:
    plan = QueryRouter().route("Order Service 发布后出现大量 5xx，应如何定位问题并判断是否回滚？")
    assert plan.intent is RetrievalIntent.MULTI_DOCUMENT
    assert plan.strategy is RetrievalStrategy.HYBRID


def test_overview_routes_to_global() -> None:
    plan = QueryRouter().route("整个系统的核心组件和关系是什么？")
    assert plan.intent is RetrievalIntent.OVERVIEW
    assert plan.strategy is RetrievalStrategy.GLOBAL


def test_unclear_routes_to_explicit_general_fallback() -> None:
    plan = QueryRouter().route("你能介绍一下这里吗？")
    assert plan.intent is RetrievalIntent.GENERAL
    assert plan.strategy is RetrievalStrategy.HYBRID
    #: a normal unclear route is not a *raised* fallback: fallback_used stays False
    #: unless the router actually errored while routing.
    router = QueryRouter()
    router.route("你能介绍一下这里吗？")
    assert router.last_decision is not None
    assert router.last_decision.fallback_used is False


def test_router_exposes_plan_fields() -> None:
    plan = QueryRouter(default_top_k=15).route("Access token 的有效期是多少？")
    assert isinstance(plan, RetrievalPlan)
    assert plan.top_k == 15
    assert plan.enable_rerank is False
    assert plan.reason  #: decision is explainable
