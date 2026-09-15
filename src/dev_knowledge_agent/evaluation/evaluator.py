"""Evaluation glue: turn an AgentResult + its trace into an ``EvalCaseResult``.

Pure transformation logic, no real agent run here -- the runner (or the
CLI) owns the actual LLM call. ``evaluation/`` never imports LightRAG or a
provider SDK (architecture guard).
"""

from __future__ import annotations

from dev_knowledge_agent.agent.models import AgentResult
from dev_knowledge_agent.evaluation.metrics import (
    answer_term_match,
    citation_grounded,
    citation_source_recall,
    classify_failure,
    detect_abstention,
    source_recall,
)
from dev_knowledge_agent.evaluation.models import EvalCase, EvalCaseResult
from dev_knowledge_agent.observability.analysis import (
    agent_latency_ms,
    sum_attributes,
)
from dev_knowledge_agent.observability.models import (
    FailureCategory,
    TraceEvent,
    TraceEventType,
)

__all__ = ["build_case_result"]


def build_case_result(
    case: EvalCase,
    result: AgentResult,
    events: list[TraceEvent],
) -> EvalCaseResult:
    """Derive every per-dimension verdict for one evaluated case.

    ``events`` is the trace captured during the run (may be empty if the
    caller did not capture one -- actuals still come from ``AgentResult``).
    """
    tool_called = bool(result.tool_calls)

    #: actual routing comes from the first tool record that surfaced one.
    actual_intent = None
    actual_strategy = None
    fallback_used = False
    for record in result.tool_calls:
        if record.routing is not None:
            actual_intent = record.routing.intent
            actual_strategy = record.routing.strategy
            fallback_used = fallback_used or record.routing.fallback_used

    actual_sources: list[str] = []
    for record in result.tool_calls:
        for source in record.sources:
            if source not in actual_sources:
                actual_sources.append(source)

    no_evidence = any(r.result_status == "NO_EVIDENCE" for r in result.tool_calls)
    abstained = detect_abstention(result)
    matched, missing = answer_term_match(result.answer, case.expected_answer_terms)

    intent_match: bool | None = None
    if case.expected_intent is not None:
        intent_match = actual_intent == case.expected_intent
    strategy_match: bool | None = None
    if case.expected_strategy is not None:
        strategy_match = actual_strategy == case.expected_strategy

    grounded = citation_grounded(result.citations, actual_sources)
    citation_recall = citation_source_recall(case.expected_sources, result.citations)

    failure_category = classify_failure(result)
    #: a groundedness miss is a citation failure when no harder failure exists
    if failure_category is None and grounded is False and result.citations:
        failure_category = FailureCategory.CITATION_ERROR

    return EvalCaseResult(
        case_id=case.id,
        query=case.query,
        category=case.category,
        should_call_tool=case.should_call_tool,
        expected_intent=case.expected_intent,
        expected_strategy=case.expected_strategy,
        expected_sources=case.expected_sources,
        expected_answer_terms=case.expected_answer_terms,
        expect_abstain=case.expect_abstain,
        status=result.status.value,
        tool_called=tool_called,
        actual_intent=actual_intent,
        actual_strategy=actual_strategy,
        fallback_used=fallback_used,
        no_evidence=no_evidence,
        actual_sources=actual_sources,
        citations=result.citations,
        answer=result.answer,
        abstained=abstained,
        tool_selection_correct=case.should_call_tool == tool_called,
        intent_match=intent_match,
        strategy_match=strategy_match,
        source_recall=source_recall(case.expected_sources, actual_sources),
        answer_matched_terms=matched,
        answer_missing_terms=missing,
        answer_terms_all_present=None if not case.expected_answer_terms else not missing,
        citation_grounded=grounded,
        citation_source_recall=citation_recall,
        trace_id=result.trace_id,
        latency_ms=agent_latency_ms(events),
        input_tokens=sum_attributes(events, TraceEventType.MODEL_CALL_COMPLETED, "input_tokens")
        or None,
        output_tokens=sum_attributes(events, TraceEventType.MODEL_CALL_COMPLETED, "output_tokens")
        or None,
        total_tokens=sum_attributes(events, TraceEventType.MODEL_CALL_COMPLETED, "total_tokens")
        or None,
        failure_category=failure_category,
        failure_message=result.error,
    )
