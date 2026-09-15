"""Evaluation glue: turn an AgentResult + its trace into an ``EvalCaseResult``.

Pure transformation logic, no real agent run here -- the runner (or the
CLI) owns the actual LLM call. ``evaluation/`` never imports LightRAG or a
provider SDK (architecture guard).

Stage 5.1 splits routing attribution into layers (spec §2/§21):

* Layer B (``evaluate_router_component``): route the *original* dataset
  query straight through QueryRouter -- no Agent, no rewrite. Isolates
  whether the Router policy itself is consistent.
* Layer C (``build_case_result``): the Agent's actual request. The primary
  routing decision is the *first* ``RoutingStep``; later steps never
  overwrite it (spec §6-§8).
* ``query_rewrite_drift``: the Agent's rewritten ``tool_query`` lost the
  retrieval signal (critical terms dropped, or the Router routes the
  original query to the expected intent while the rewritten one does not).
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
from dev_knowledge_agent.evaluation.models import (
    EvalCase,
    EvalCaseResult,
    RouterComponentResult,
    RouterComponentRunResult,
)
from dev_knowledge_agent.observability.analysis import (
    agent_latency_ms,
    sum_attributes,
)
from dev_knowledge_agent.observability.models import (
    FailureCategory,
    TraceEvent,
    TraceEventType,
)
from dev_knowledge_agent.retrieval.models import RoutingStep
from dev_knowledge_agent.retrieval.router import QueryRouter

__all__ = [
    "build_case_result",
    "evaluate_router_component",
    "merge_router_component",
]


def _primary_step(routing_steps: list[RoutingStep]) -> RoutingStep | None:
    """Layer C primary decision = the first routing step (spec §7/§21)."""
    return routing_steps[0] if routing_steps else None


def _term_preservation(terms: list[str], tool_query: str | None) -> tuple[list[str], list[str]]:
    """Split ``terms`` into preserved / missing substrings of the tool query.

    ``tool_query=None`` (no tool call surfaced a routing step) -> nothing
    preserved, everything missing; the caller decides applicability.
    """
    if not terms:
        return [], []
    if tool_query is None:
        return [], list(terms)
    preserved = [t for t in terms if t in tool_query]
    missing = [t for t in terms if t not in tool_query]
    return preserved, missing


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

    #: ---- Layer C: agentic retrieval, primary = first routing step (spec §7) ----
    routing_steps: list[RoutingStep] = list(result.routing_steps)
    primary = _primary_step(routing_steps)
    tool_query = primary.tool_query if primary else None
    query_rewritten: bool | None = (
        primary.original_user_query != primary.tool_query if primary else None
    )
    primary_intent = primary.intent if primary else None
    primary_strategy = primary.strategy if primary else None
    primary_fallback_used = primary.fallback_used if primary else False

    primary_intent_match: bool | None = None
    if case.expected_intent is not None and primary_intent is not None:
        primary_intent_match = primary_intent == case.expected_intent
    primary_strategy_match: bool | None = None
    if case.expected_strategy is not None and primary_strategy is not None:
        primary_strategy_match = primary_strategy == case.expected_strategy

    #: ---- query rewrite preservation (spec §13/§14) ----
    preserved, missing = _term_preservation(case.critical_terms, tool_query)
    preservation_rate: float | None = None
    if case.critical_terms:
        preservation_rate = round(len(preserved) / len(case.critical_terms), 4)
    #: term-level drift: a rewritten tool query dropped a critical term.
    query_rewrite_drift = bool(missing)

    actual_sources: list[str] = []
    for record in result.tool_calls:
        for source in record.sources:
            if source not in actual_sources:
                actual_sources.append(source)

    no_evidence = any(r.result_status == "NO_EVIDENCE" for r in result.tool_calls)
    abstained = detect_abstention(result)
    matched, missing_terms = answer_term_match(result.answer, case.expected_answer_terms)

    grounded = citation_grounded(result.citations, actual_sources)
    citation_recall = citation_source_recall(case.expected_sources, result.citations)

    failure_category = classify_failure(result)
    #: an intent-drifting rewrite is an Agent -> tool-query interface problem
    #: (spec §32) when no harder failure already explains the case.
    if failure_category is None and query_rewrite_drift:
        failure_category = FailureCategory.QUERY_REWRITE_INTENT_DRIFT
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
        critical_terms=case.critical_terms,
        status=result.status.value,
        tool_called=tool_called,
        no_evidence=no_evidence,
        actual_sources=actual_sources,
        citations=result.citations,
        answer=result.answer,
        abstained=abstained,
        #: Layer C
        routing_steps=routing_steps,
        tool_query=tool_query,
        query_rewritten=query_rewritten,
        primary_intent=primary_intent,
        primary_strategy=primary_strategy,
        primary_fallback_used=primary_fallback_used,
        primary_intent_match=primary_intent_match,
        primary_strategy_match=primary_strategy_match,
        query_rewrite_drift=query_rewrite_drift,
        #: per-dimension verdicts
        tool_selection_correct=case.should_call_tool == tool_called,
        source_recall=source_recall(case.expected_sources, actual_sources),
        answer_matched_terms=matched,
        answer_missing_terms=missing_terms,
        answer_terms_all_present=None if not case.expected_answer_terms else not missing_terms,
        citation_grounded=grounded,
        citation_source_recall=citation_recall,
        #: query rewrite preservation
        critical_terms_preserved=preserved,
        critical_terms_missing=missing,
        critical_term_preservation_rate=preservation_rate,
        #: observability / cost
        trace_id=result.trace_id,
        latency_ms=agent_latency_ms(events),
        input_tokens=sum_attributes(events, TraceEventType.MODEL_CALL_COMPLETED, "input_tokens")
        or None,
        output_tokens=sum_attributes(events, TraceEventType.MODEL_CALL_COMPLETED, "output_tokens")
        or None,
        total_tokens=sum_attributes(events, TraceEventType.MODEL_CALL_COMPLETED, "total_tokens")
        or None,
        model_calls=sum(1 for e in events if e.event_type is TraceEventType.MODEL_CALL_COMPLETED)
        or None,
        tool_call_count=len(result.tool_calls),
        failure_category=failure_category,
        failure_message=result.error,
    )


def evaluate_router_component(
    cases: list[EvalCase],
    router: QueryRouter,
) -> RouterComponentRunResult:
    """Layer B: route each *original* dataset query through QueryRouter.

    No Agent, no tool calling, no LLM rewrite (spec §3) -- this isolates
    whether the Router policy classifies the user's original query
    correctly, independent of anything the Agent does afterwards.
    """
    results: list[RouterComponentResult] = []
    for case in cases:
        plan = router.route(case.query)
        decision = router.last_decision
        actual_intent = decision.intent if decision is not None else plan.intent
        actual_strategy = decision.strategy if decision is not None else plan.strategy
        fallback_used = decision.fallback_used if decision is not None else False
        results.append(
            RouterComponentResult(
                case_id=case.id,
                query=case.query,
                expected_intent=case.expected_intent,
                expected_strategy=case.expected_strategy,
                actual_intent=actual_intent,
                actual_strategy=actual_strategy,
                fallback_used=fallback_used,
                reason=decision.reason if decision is not None else plan.reason,
                intent_match=(
                    case.expected_intent == actual_intent
                    if case.expected_intent is not None
                    else None
                ),
                strategy_match=(
                    case.expected_strategy == actual_strategy
                    if case.expected_strategy is not None
                    else None
                ),
            )
        )
    from datetime import datetime, timezone

    from dev_knowledge_agent.evaluation.metrics import router_component_metrics

    return RouterComponentRunResult(
        run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        cases=results,
        metrics=router_component_metrics(results),
    )


def merge_router_component(
    case_results: list[EvalCaseResult],
    router_results: list[RouterComponentResult],
) -> list[EvalCaseResult]:
    """Attach Layer B router verdicts to the matching Layer C case results.

    Also upgrades ``query_rewrite_drift`` with the intent-flip signal: the
    Router routes the *original* query to the expected intent while the
    Agent's rewritten tool-query step did not -> the rewrite, not the
    Router, is what drifted (spec §19).
    """
    by_id = {r.case_id: r for r in router_results}
    merged: list[EvalCaseResult] = []
    for case_result in case_results:
        router_result = by_id.get(case_result.case_id)
        if router_result is None:
            merged.append(case_result)
            continue
        intent_flip = (
            router_result.intent_match is True and case_result.primary_intent_match is False
        )
        drift = case_result.query_rewrite_drift or intent_flip
        merged.append(
            case_result.model_copy(
                update={
                    "router_intent_match": router_result.intent_match,
                    "router_strategy_match": router_result.strategy_match,
                    "router_fallback_used": router_result.fallback_used,
                    "query_rewrite_drift": drift,
                }
            )
        )
    return merged
