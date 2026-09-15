"""Evaluation metrics (Stage 5) -- deterministic, interpretable.

Prefer explicit, small, explainable metrics over fake "answer_quality =
0.93" numbers (spec §13/§17). No complex IR metrics (NDCG/MAP/MRR) until
the dataset actually has graded relevance -- the current KB is tiny.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence

from dev_knowledge_agent.agent.models import AgentResult, AgentStatus
from dev_knowledge_agent.evaluation.models import (
    EvalCaseResult,
    MetricSummary,
    RouterComponentResult,
    RouterComponentSummary,
)
from dev_knowledge_agent.observability.models import FailureCategory

__all__ = [
    "ConfusionCounts",
    "abstention_accuracy",
    "answer_term_match",
    "citation_grounded",
    "citation_source_recall",
    "classify_failure",
    "compute_metrics",
    "confusion_counts",
    "detect_abstention",
    "expected_source_recall",
    "mean_or_none",
    "percentile_or_none",
    "router_component_metrics",
    "source_recall",
]

#: Heuristic abstention phrases (spec §18) -- this is NOT claim-level
#: hallucination detection (spec §19); it only flags "no internal fact given".
_ABSTENTION_PHRASES = (
    "没有",
    "未提供",
    "没有提供",
    "无法",
    "不足",
    "不够",
    "没有找到",
    "不包含",
    "未能",
    "not enough information",
    "no evidence",
    "not available",
    "insufficient",
    "cannot answer",
    "not covered",
    "not in the knowledge base",
)


def mean_or_none(values: Sequence[float]) -> float | None:
    """Arithmetic mean, None when empty (no pretending significance)."""
    return round(statistics.fmean(values), 4) if values else None


def percentile_or_none(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * p / 100.0
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower
    return round(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight, 1)


class ConfusionCounts:
    """Tool-selection confusion matrix (spec §8)."""

    def __init__(self, tp: int, tn: int, fp: int, fn: int) -> None:
        self.tp = tp
        self.tn = tn
        self.fp = fp
        self.fn = fn

    @property
    def accuracy(self) -> float:
        total = self.tp + self.tn + self.fp + self.fn
        return (self.tp + self.tn) / total if total else 0.0

    @property
    def precision(self) -> float | None:
        denom = self.tp + self.fp
        return self.tp / denom if denom else None

    @property
    def recall(self) -> float | None:
        denom = self.tp + self.fn
        return self.tp / denom if denom else None


def confusion_counts(should_call: list[bool], tool_called: list[bool]) -> ConfusionCounts:
    """Build the confusion matrix for parallel expected/actual booleans."""
    tp = tn = fp = fn = 0
    for expected, actual in zip(should_call, tool_called, strict=True):
        if expected and actual:
            tp += 1
        elif expected and not actual:
            fn += 1  #: severe: should have consulted the Tool but did not
        elif not expected and actual:
            fp += 1
        else:
            tn += 1
    return ConfusionCounts(tp=tp, tn=tn, fp=fp, fn=fn)


def source_recall(expected_sources: list[str], actual_sources: list[str]) -> float | None:
    """Fraction of expected sources actually retrieved (spec §12).

    Extra retrieved sources do NOT fail the case. None when the case has no
    expected sources (metric not applicable).
    """
    if not expected_sources:
        return None
    expected = set(expected_sources)
    actual = set(actual_sources)
    return round(len(expected & actual) / len(expected), 4)


def expected_source_recall(results: list[EvalCaseResult]) -> float | None:
    """Mean source recall over cases that declared expected sources."""
    values = [r.source_recall for r in results if r.source_recall is not None]
    return mean_or_none(values)


def citation_grounded(citations: list[str], tool_sources: list[str]) -> bool | None:
    """Every final citation must exist in the tool-returned citations (§14).

    None when the Agent cited nothing (nothing to check).
    """
    if not citations:
        return None
    return all(c in set(tool_sources) for c in citations)


def citation_source_recall(expected_sources: list[str], citations: list[str]) -> float | None:
    """Fraction of expected sources actually cited in the final answer (§15)."""
    if not expected_sources:
        return None
    return round(len(set(expected_sources) & set(citations)) / len(expected_sources), 4)


def answer_term_match(answer: str, terms: list[str]) -> tuple[list[str], list[str]]:
    """Split ``terms`` into matched / missing substrings of the answer (§16)."""
    if not terms:
        return [], []
    matched = [t for t in terms if t in answer]
    missing = [t for t in terms if t not in answer]
    return matched, missing


def detect_abstention(result: AgentResult) -> bool:
    """Structured abstention signal (§18): NO_EVIDENCE path or abstention language."""
    if any(r.result_status == "NO_EVIDENCE" for r in result.tool_calls):
        return True
    low = (result.answer or "").lower()
    return any(phrase in low for phrase in _ABSTENTION_PHRASES)


def abstention_accuracy(results: list[EvalCaseResult]) -> float | None:
    """Fraction of ``expect_abstain=True`` cases that actually abstained (§18)."""
    relevant = [r for r in results if r.expect_abstain]
    if not relevant:
        return None
    return round(sum(1 for r in relevant if r.abstained) / len(relevant), 4)


def classify_failure(result: AgentResult) -> FailureCategory | None:
    """Map an AgentResult onto the failure taxonomy (spec §32).

    ``None`` means no failure. NO_EVIDENCE is a *business* abstention result
    and is only reported when no harder (ERROR-family) failure exists.
    """
    if result.status is AgentStatus.MODEL_ERROR:
        return FailureCategory.MODEL_ERROR
    if result.status is AgentStatus.MAX_STEPS_EXCEEDED:
        return FailureCategory.MAX_STEPS
    if result.status is AgentStatus.TOOL_ERROR:
        if result.error and "max_tool_calls" in result.error:
            return FailureCategory.MAX_TOOL_CALLS
        return FailureCategory.TOOL_ERROR
    for record in result.tool_calls:
        if record.result_status == "unknown_tool":
            return FailureCategory.UNKNOWN_TOOL
        if record.result_status == "invalid_arguments":
            return FailureCategory.INVALID_TOOL_ARGUMENTS
    for record in result.tool_calls:
        if record.result_status == "NO_EVIDENCE":
            return FailureCategory.NO_EVIDENCE
    return None


def router_component_metrics(results: list[RouterComponentResult]) -> RouterComponentSummary:
    """Layer B aggregate: QueryRouter acting on the ORIGINAL query (spec §3/§27).

    This is *policy consistency* against the project baseline expectation,
    independent of the Agent / rewrite chain.
    """
    if not results:
        return RouterComponentSummary()
    intent_values = [r.intent_match for r in results if r.intent_match is not None]
    strategy_values = [r.strategy_match for r in results if r.strategy_match is not None]
    fallback_values = [float(r.fallback_used) for r in results]
    return RouterComponentSummary(
        intent_accuracy=mean_or_none(intent_values),
        strategy_accuracy=mean_or_none(strategy_values),
        fallback_rate=mean_or_none(fallback_values),
    )


def compute_metrics(results: list[EvalCaseResult]) -> MetricSummary:
    """Aggregate a list of per-case results into one MetricSummary (§42).

    Routing metrics are layered (Stage 5.1, spec §3/§7/§21): Layer B reads
    the ``router_component_*` fields (original-query pass), Layer C reads the
    primary routing step fields. There is no single blended "routing
    accuracy" anymore.
    """
    if not results:
        return MetricSummary()

    expected_tool = [r.should_call_tool for r in results]
    actual_tool = [r.tool_called for r in results]
    conf = confusion_counts(expected_tool, actual_tool)

    #: Layer B -- router component (merged original-query pass, if run)
    router_intent_values = [
        r.router_intent_match for r in results if r.router_intent_match is not None
    ]
    router_strategy_values = [
        r.router_strategy_match for r in results if r.router_strategy_match is not None
    ]
    router_fallback_values = [float(r.router_fallback_used) for r in results]

    #: Layer C -- agentic retrieval, primary step only
    primary_intent_values = [
        r.primary_intent_match for r in results if r.primary_intent_match is not None
    ]
    primary_strategy_values = [
        r.primary_strategy_match for r in results if r.primary_strategy_match is not None
    ]
    tool_called_cases = [r for r in results if r.tool_called]
    primary_fallback_values = [float(r.primary_fallback_used) for r in tool_called_cases]
    all_steps = sum(len(r.routing_steps) for r in results)
    drift_values = [r.query_rewrite_drift for r in results]

    source_values = [r.source_recall for r in results if r.source_recall is not None]
    grounded_values = [r.citation_grounded for r in results if r.citation_grounded is not None]
    citation_recall_values = [
        r.citation_source_recall for r in results if r.citation_source_recall is not None
    ]
    term_values = [
        bool(r.answer_terms_all_present) for r in results if r.answer_terms_all_present is not None
    ]
    preservation_values = [
        r.critical_term_preservation_rate
        for r in results
        if r.critical_term_preservation_rate is not None
    ]
    latency_values = [r.latency_ms for r in results if r.latency_ms is not None]

    #: failures; NO_EVIDENCE / QUERY_REWRITE_INTENT_DRIFT are business or
    #: diagnostic outcomes, not system errors -- excluded from failed_case_ids.
    business_categories = {
        FailureCategory.NO_EVIDENCE.value,
        FailureCategory.QUERY_REWRITE_INTENT_DRIFT.value,
    }
    failures = [r for r in results if r.failure_category is not None]
    failure_counts: dict[str, int] = Counter(
        r.failure_category.value for r in failures if r.failure_category is not None
    )
    hard_failures = [
        r
        for r in failures
        if r.failure_category is not None and r.failure_category.value not in business_categories
    ]

    total_input = sum(r.input_tokens for r in results if r.input_tokens is not None)
    total_output = sum(r.output_tokens for r in results if r.output_tokens is not None)
    total_all = sum(r.total_tokens for r in results if r.total_tokens is not None)
    any_tokens = any(r.total_tokens is not None for r in results)

    return MetricSummary(
        sample_count=len(results),
        tool_selection_accuracy=round(conf.accuracy, 4),
        tool_call_precision=round(conf.precision, 4) if conf.precision is not None else None,
        tool_call_recall=round(conf.recall, 4) if conf.recall is not None else None,
        false_positive_count=conf.fp,
        false_negative_count=conf.fn,
        #: Layer B
        router_component_intent_accuracy=mean_or_none(router_intent_values),
        router_component_strategy_accuracy=mean_or_none(router_strategy_values),
        router_component_fallback_rate=mean_or_none(router_fallback_values),
        #: Layer C
        primary_intent_accuracy=mean_or_none(primary_intent_values),
        primary_strategy_accuracy=mean_or_none(primary_strategy_values),
        all_routing_steps_count=all_steps,
        routing_fallback_rate=mean_or_none(primary_fallback_values),
        query_rewrite_drift_count=sum(1 for d in drift_values if d),
        expected_source_recall=mean_or_none(source_values),
        no_evidence_rate=mean_or_none([float(r.no_evidence) for r in results]),
        citation_grounded_rate=mean_or_none(grounded_values),
        citation_source_recall=mean_or_none(citation_recall_values),
        answer_term_match_rate=mean_or_none(term_values),
        abstention_accuracy=abstention_accuracy(results),
        critical_term_preservation_rate=mean_or_none(preservation_values),
        latency_p50_ms=percentile_or_none(latency_values, 50),
        latency_p95_ms=percentile_or_none(latency_values, 95),
        total_input_tokens=total_input if any_tokens else None,
        total_output_tokens=total_output if any_tokens else None,
        total_tokens=total_all if any_tokens else None,
        tokens_per_case=mean_or_none(
            [float(r.total_tokens) for r in results if r.total_tokens is not None]
        ),
        model_calls_per_case=mean_or_none(
            [float(r.model_calls) for r in results if r.model_calls is not None]
        ),
        tool_calls_per_case=mean_or_none([float(r.tool_call_count) for r in results]),
        failure_counts=dict(failure_counts),
        failed_case_ids=[r.case_id for r in hard_failures],
    )
