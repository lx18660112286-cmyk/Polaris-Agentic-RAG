"""Offline tests for derivation of per-case verdicts (spec §8-§18, §28).

Stage 5.1: Layer C verdicts come from the AgentResult's ``routing_steps``
(primary = first step); query-rewrite drift is attributed from critical-term
loss; Layer B router verdicts are merged via ``merge_router_component``.
"""

from __future__ import annotations

from dev_knowledge_agent.agent.models import AgentResult, AgentStatus, ToolCallRecord
from dev_knowledge_agent.evaluation.evaluator import (
    build_case_result,
    evaluate_router_component,
    merge_router_component,
)
from dev_knowledge_agent.evaluation.models import EvalCase
from dev_knowledge_agent.retrieval.models import (
    RetrievalIntent,
    RetrievalStrategy,
    RoutingStep,
)
from dev_knowledge_agent.retrieval.router import QueryRouter


def _routing_intent() -> RetrievalIntent:
    return RetrievalIntent.FACTUAL


def _step(
    tool_query: str = "Access token 的有效期是多少？",
    intent: RetrievalIntent = RetrievalIntent.FACTUAL,
    strategy: RetrievalStrategy = RetrievalStrategy.FOCUSED,
    fallback_used: bool = False,
) -> RoutingStep:
    return RoutingStep(
        step_index=0,
        tool_call_id="call_1",
        original_user_query="Access token 的有效期是多少？",
        tool_query=tool_query,
        intent=intent,
        strategy=strategy,
        reason="value query",
        fallback_used=fallback_used,
    )


def _record(
    status: str = "SUCCESS",
    sources: list[str] | None = None,
) -> ToolCallRecord:
    return ToolCallRecord(
        name="search_dev_knowledge",
        arguments={},
        result_status=status,
        sources=list(sources or []),
    )


def test_success_case_derives_verdicts() -> None:
    case = EvalCase(
        id="f1",
        query="Access token 的有效期是多少？",
        category="factual",
        should_call_tool=True,
        expected_intent=RetrievalIntent.FACTUAL,
        expected_strategy=RetrievalStrategy.FOCUSED,
        expected_sources=["api_auth.md"],
        expected_answer_terms=["30", "分钟"],
    )
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        answer="access token 有效期 30 分钟",
        citations=["api_auth.md"],
        tool_calls=[_record(sources=["api_auth.md"])],
        original_query="Access token 的有效期是多少？",
        routing_steps=[_step()],
        trace_id="t1",
    )
    case_result = build_case_result(case, result, events=[])
    assert case_result.tool_selection_correct is True
    assert case_result.primary_intent_match is True
    assert case_result.primary_strategy_match is True
    assert case_result.primary_intent is RetrievalIntent.FACTUAL
    assert case_result.primary_strategy is RetrievalStrategy.FOCUSED
    assert case_result.query_rewritten is False
    assert case_result.source_recall == 1.0
    assert case_result.citation_grounded is True
    assert case_result.answer_terms_all_present is True
    assert case_result.answer_missing_terms == []
    assert case_result.trace_id == "t1"


def test_primary_routing_uses_first_step_not_last() -> None:
    """Later routing steps must never overwrite the primary verdict (§6-§8)."""
    case = EvalCase(
        id="m1",
        query="q",
        category="factual",
        should_call_tool=True,
        expected_intent=RetrievalIntent.FACTUAL,
        expected_strategy=RetrievalStrategy.FOCUSED,
    )
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        answer="ok",
        tool_calls=[_record()],
        original_query="q",
        routing_steps=[
            _step(intent=RetrievalIntent.FACTUAL, strategy=RetrievalStrategy.FOCUSED),
            RoutingStep(
                step_index=1,
                tool_call_id="call_2",
                original_user_query="q",
                tool_query="billing 数据库",
                intent=RetrievalIntent.MULTI_DOCUMENT,
                strategy=RetrievalStrategy.HYBRID,
                reason="second probe",
            ),
        ],
    )
    case_result = build_case_result(case, result, events=[])
    assert case_result.primary_intent is RetrievalIntent.FACTUAL
    assert case_result.primary_strategy is RetrievalStrategy.FOCUSED
    assert case_result.primary_intent_match is True
    assert case_result.primary_strategy_match is True


def test_critical_term_preservation_and_drift() -> None:
    """A rewritten tool query that drops a critical term => drift (§13/§14)."""
    case = EvalCase(
        id="r1",
        query="Access token 的有效期是多少？",
        category="factual",
        should_call_tool=True,
        critical_terms=["Access token", "有效期"],
    )
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        answer="30 分钟",
        tool_calls=[_record()],
        original_query="Access token 的有效期是多少？",
        routing_steps=[
            _step(tool_query="token 多久过期", intent=RetrievalIntent.GENERAL),
        ],
    )
    case_result = build_case_result(case, result, events=[])
    assert case_result.query_rewritten is True
    assert case_result.critical_terms_preserved == []  #: both terms lost
    assert set(case_result.critical_terms_missing) == {"Access token", "有效期"}
    assert case_result.critical_term_preservation_rate == 0.0
    assert case_result.query_rewrite_drift is True
    #: drift is attributed as an Agent -> tool-query interface problem (§32).
    from dev_knowledge_agent.observability.models import FailureCategory

    assert case_result.failure_category is FailureCategory.QUERY_REWRITE_INTENT_DRIFT


def test_no_drift_when_tool_query_keeps_critical_terms() -> None:
    case = EvalCase(
        id="r2",
        query="Access token 的有效期是多少？",
        category="factual",
        should_call_tool=True,
        critical_terms=["Access token", "有效期"],
    )
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        answer="30 分钟",
        tool_calls=[_record()],
        original_query="Access token 的有效期是多少？",
        routing_steps=[_step(tool_query="Access token 有效期多少分钟")],
    )
    case_result = build_case_result(case, result, events=[])
    assert set(case_result.critical_terms_preserved) == {"Access token", "有效期"}
    assert case_result.critical_terms_missing == []
    assert case_result.critical_term_preservation_rate == 1.0
    assert case_result.query_rewrite_drift is False
    assert case_result.failure_category is None


def test_hallucinated_citation_fails_groundedness() -> None:
    case = EvalCase(id="x", query="q", category="factual", should_call_tool=True)
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        answer="billing 用 postgres",
        citations=["billing.md"],  #: never returned by the Tool -> hallucinated
        tool_calls=[_record(sources=["api_auth.md"])],
    )
    case_result = build_case_result(case, result, events=[])
    assert case_result.citation_grounded is False


def test_fn_when_should_call_but_not_called() -> None:
    case = EvalCase(id="f1", query="q", category="factual", should_call_tool=True)
    result = AgentResult(status=AgentStatus.SUCCESS, answer="直接回答了")
    case_result = build_case_result(case, result, events=[])
    assert case_result.tool_selection_correct is False  #: False Negative


def test_no_evidence_honest_abstention() -> None:
    case = EvalCase(
        id="u1",
        query="Billing Service 使用什么数据库？",
        category="unknown",
        should_call_tool=True,
        expect_abstain=True,
    )
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        answer="知识库中没有 Billing Service 的信息。",
        tool_calls=[_record(status="NO_EVIDENCE")],
    )
    case_result = build_case_result(case, result, events=[])
    assert case_result.abstained is True
    assert case_result.no_evidence is True
    assert case_result.citation_grounded is None  #: nothing cited, nothing to check


# --------------------------------------------------------------------------- #
# Layer B -- Router Component (spec §3/§28)
# --------------------------------------------------------------------------- #


def test_agentic_routing_eval_uses_tool_query() -> None:
    """Layer C verdicts describe the Agent's *actual* tool query, not the
    original user message (spec §4)."""
    case = EvalCase(
        id="a1",
        query="Access token 的有效期是多少？",
        category="factual",
        should_call_tool=True,
        expected_intent=RetrievalIntent.TERMINOLOGY,
        expected_strategy=RetrievalStrategy.HYBRID,
    )
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        answer="ok",
        tool_calls=[_record()],
        original_query="Access token 的有效期是多少？",
        routing_steps=[
            _step(
                tool_query="token 过期时间说明",
                intent=RetrievalIntent.TERMINOLOGY,
                strategy=RetrievalStrategy.HYBRID,
            )
        ],
    )
    case_result = build_case_result(case, result, events=[])
    #: the layer-C verdict is about the rewritten tool query, not the original.
    assert case_result.tool_query == "token 过期时间说明"
    assert case_result.query_rewritten is True
    assert case_result.primary_intent is RetrievalIntent.TERMINOLOGY
    assert case_result.primary_strategy is RetrievalStrategy.HYBRID
    assert case_result.primary_intent_match is True
    assert case_result.primary_strategy_match is True


def test_router_component_bypasses_agent() -> None:
    """Original-query routing is evaluated without any Agent rewrite."""
    cases = [
        EvalCase(
            id="b1",
            query="Access token 的有效期是多少？",
            category="factual",
            expected_intent=RetrievalIntent.FACTUAL,
            expected_strategy=RetrievalStrategy.FOCUSED,
        ),
        EvalCase(
            id="b2",
            query="系统整体架构是什么样的？",
            category="overview",
            expected_intent=RetrievalIntent.OVERVIEW,
            expected_strategy=RetrievalStrategy.GLOBAL,
        ),
    ]
    router = QueryRouter()
    run = evaluate_router_component(cases, router)
    assert len(run.cases) == 2
    assert all(c.intent_match is True for c in run.cases)
    assert run.metrics.intent_accuracy == 1.0
    assert run.metrics.strategy_accuracy == 1.0
    assert run.metrics.fallback_rate == 0.0


def test_merge_router_component_attributes_intent_flip_drift() -> None:
    """Router routes the original correctly, the Agent's rewrite does not:
    the drift belongs to the query rewrite, not the Router (§19)."""
    case = EvalCase(
        id="d1",
        query="Access token 的有效期是多少？",
        category="factual",
        expected_intent=RetrievalIntent.FACTUAL,
        #: no critical-term labels -> the only drift signal is the intent flip.
    )
    #: Agent's tool query lost the marker -> Layer C routed as GENERAL.
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        answer="30 分钟",
        tool_calls=[_record()],
        original_query=case.query,
        routing_steps=[_step(tool_query="token 多久过期", intent=RetrievalIntent.GENERAL)],
    )
    built = build_case_result(case, result, events=[])
    assert built.primary_intent_match is False  #: rewritten query drifted
    assert built.query_rewrite_drift is False  #: no term labels -> no term signal

    router = QueryRouter()
    merged = merge_router_component([built], evaluate_router_component([case], router).cases)[0]
    assert merged.router_intent_match is True  #: Router was right on the original
    assert merged.query_rewrite_drift is True  #: flip is attributed to the rewrite
