"""Offline tests for derivation of per-case verdicts (spec §8-§18)."""

from __future__ import annotations

from dev_knowledge_agent.agent.models import AgentResult, AgentStatus, ToolCallRecord
from dev_knowledge_agent.evaluation.evaluator import build_case_result
from dev_knowledge_agent.evaluation.models import EvalCase
from dev_knowledge_agent.retrieval.models import (
    RetrievalIntent,
    RetrievalStrategy,
    RoutingDecision,
)


def _routing() -> RoutingDecision:
    return RoutingDecision(
        intent=RetrievalIntent.FACTUAL,
        strategy=RetrievalStrategy.FOCUSED,
        reason="value query",
    )


def _record(
    status: str = "SUCCESS",
    sources: list[str] | None = None,
    routing: RoutingDecision | None = None,
) -> ToolCallRecord:
    return ToolCallRecord(
        name="search_dev_knowledge",
        arguments={},
        result_status=status,
        sources=list(sources or []),
        routing=routing,
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
        tool_calls=[_record(sources=["api_auth.md"], routing=_routing())],
        trace_id="t1",
    )
    case_result = build_case_result(case, result, events=[])
    assert case_result.tool_selection_correct is True
    assert case_result.intent_match is True
    assert case_result.strategy_match is True
    assert case_result.source_recall == 1.0
    assert case_result.citation_grounded is True
    assert case_result.answer_terms_all_present is True
    assert case_result.answer_missing_terms == []
    assert case_result.trace_id == "t1"


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
