"""Offline tests for evaluation metrics (spec §8-§18, §46-§48).

Everything here is deterministic and offline: no LLM, no LightRAG. The
tests build ``EvalCaseResult`` objects directly and assert the exact
verdicts computed by ``evaluation/metrics.py``.
"""

from __future__ import annotations

from polaris_agentic_rag.agent.models import AgentResult, AgentStatus, ToolCallRecord
from polaris_agentic_rag.evaluation.metrics import (
    abstention_accuracy,
    answer_term_match,
    citation_grounded,
    citation_source_recall,
    compute_metrics,
    confusion_counts,
    detect_abstention,
    expected_source_recall,
    router_component_metrics,
    source_recall,
)
from polaris_agentic_rag.evaluation.models import (
    EvalCaseResult,
    RouterComponentResult,
)
from polaris_agentic_rag.observability.models import FailureCategory
from polaris_agentic_rag.retrieval.models import RetrievalIntent, RetrievalStrategy

# --------------------------------------------------------------------------- #
# Tool selection confusion matrix (spec §8 / §46)
# --------------------------------------------------------------------------- #


def test_confusion_tp() -> None:
    conf = confusion_counts([True, False, True, False], [True, False, True, False])
    assert (conf.tp, conf.tn, conf.fp, conf.fn) == (2, 2, 0, 0)
    assert conf.accuracy == 1.0
    assert conf.precision == 1.0
    assert conf.recall == 1.0


def test_confusion_fp_and_fn_are_separate() -> None:
    #: expected should-tool but agent called nothing -> FN (severe)
    conf = confusion_counts([True, False], [False, True])
    assert conf.fn == 1  #: missed a tool call
    assert conf.fp == 1  #: called a tool unnecessarily
    assert conf.accuracy == 0.0
    assert conf.precision == 0.0
    assert conf.recall == 0.0


def test_confusion_accuracy_partial() -> None:
    conf = confusion_counts([True, True, False, False], [True, False, False, False])
    assert conf.accuracy == 0.75
    assert conf.precision == 1.0
    assert conf.recall == 0.5


# --------------------------------------------------------------------------- #
# Source recall (spec §11-§12)
# --------------------------------------------------------------------------- #


def test_source_recall_full() -> None:
    assert (
        source_recall(
            ["deployment.md", "incident_runbook.md"],
            ["deployment.md", "incident_runbook.md", "service_overview.md"],
        )
        == 1.0
    )


def test_source_recall_partial() -> None:
    assert source_recall(["deployment.md", "incident_runbook.md"], ["deployment.md"]) == 0.5


def test_source_recall_extra_sources_do_not_fail() -> None:
    #: missing expected source is what hurts; extra retrievals do not.
    assert source_recall(["api_auth.md"], ["api_auth.md", "billing.md"]) == 1.0


def test_source_recall_none_when_no_expected() -> None:
    assert source_recall([], ["a.md"]) is None


def test_expected_source_recall_averages_over_labeled_cases() -> None:
    results = [
        EvalCaseResult(
            case_id="a",
            query="a",
            category="x",
            should_call_tool=True,
            source_recall=1.0,
        ),
        EvalCaseResult(
            case_id="b",
            query="b",
            category="x",
            should_call_tool=True,
            source_recall=0.5,
        ),
        #: no expected sources -> skipped, must not drag the mean down
        EvalCaseResult(
            case_id="c",
            query="c",
            category="x",
            should_call_tool=False,
            source_recall=None,
        ),
    ]
    assert expected_source_recall(results) == 0.75


# --------------------------------------------------------------------------- #
# Citation (spec §14-§15 / §48)
# --------------------------------------------------------------------------- #


def test_citation_grounded_valid() -> None:
    assert citation_grounded(citations=["api_auth.md"], tool_sources=["api_auth.md"]) is True


def test_citation_grounded_hallucinated() -> None:
    #: cited a file the tool never returned -> NOT grounded
    assert citation_grounded(citations=["billing.md"], tool_sources=["api_auth.md"]) is False


def test_citation_grounded_mixed() -> None:
    assert (
        citation_grounded(
            citations=["api_auth.md", "billing.md"], tool_sources=["api_auth.md", "deployment.md"]
        )
        is False
    )


def test_citation_grounded_none_when_no_citations() -> None:
    assert citation_grounded(citations=[], tool_sources=["api_auth.md"]) is None


def test_citation_source_recall() -> None:
    assert (
        citation_source_recall(
            expected_sources=["deployment.md", "api_auth.md"], citations=["api_auth.md"]
        )
        == 0.5
    )
    assert citation_source_recall([], ["a.md"]) is None  #: not applicable


# --------------------------------------------------------------------------- #
# Answer terms (spec §16-§17)
# --------------------------------------------------------------------------- #


def test_answer_term_match_all_present() -> None:
    matched, missing = answer_term_match("access token 有效期 30 分钟", ["30", "分钟"])
    assert matched == ["30", "分钟"]
    assert missing == []


def test_answer_term_match_partial() -> None:
    matched, missing = answer_term_match("token 有效期 30 秒", ["30", "分钟"])
    assert matched == ["30"]
    assert missing == ["分钟"]


def test_answer_term_match_empty_when_no_terms() -> None:
    assert answer_term_match("anything", []) == ([], [])


# --------------------------------------------------------------------------- #
# Abstention (spec §18)
# --------------------------------------------------------------------------- #


def test_detect_abstention_via_no_evidence_path() -> None:
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        answer="知识库中没有相关信息。",
        tool_calls=[ToolCallRecord(name="x", arguments={}, result_status="NO_EVIDENCE")],
    )
    assert detect_abstention(result) is True


def test_detect_abstention_via_language() -> None:
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        answer="知识库中没有提供该信息，无法回答。",
    )
    assert detect_abstention(result) is True


def test_detect_abstention_negative() -> None:
    result = AgentResult(status=AgentStatus.SUCCESS, answer="Billing 使用 postgres 数据库。")
    assert detect_abstention(result) is False


def test_abstention_accuracy() -> None:
    results = [
        #: expect abstain and actually abstained
        EvalCaseResult(
            case_id="a",
            query="a",
            category="x",
            should_call_tool=True,
            expect_abstain=True,
            abstained=True,
        ),
        #: expect abstain but answered anyway -> miss
        EvalCaseResult(
            case_id="b",
            query="b",
            category="x",
            should_call_tool=True,
            expect_abstain=True,
            abstained=False,
        ),
        #: not an abstain case -> ignored
        EvalCaseResult(
            case_id="c",
            query="c",
            category="x",
            should_call_tool=True,
            abstained=False,
        ),
    ]
    assert abstention_accuracy(results) == 0.5
    assert abstention_accuracy(results[:1]) == 1.0


# --------------------------------------------------------------------------- #
# Aggregate summary (spec §42)
# --------------------------------------------------------------------------- #


def _case_result(
    *,
    tool_called: bool,
    should_call_tool: bool = True,
    primary_intent_match: bool | None = True,
    primary_strategy_match: bool | None = True,
    router_intent_expected: bool | None = None,
    router_strategy_expected: bool | None = None,
    router_fallback: bool = False,
    drift: bool = False,
    preservation_rate: float | None = None,
    failure_category: FailureCategory | None = None,
    source_recall_val: float | None = 1.0,
    grounded: bool | None = True,
    term_ok: bool | None = True,
    latency_ms: float | None = 100.0,
    expect_abstain: bool = False,
    abstained: bool = False,
    tokens: tuple[int, int, int] | None = (10, 20, 30),
    model_calls: int | None = 2,
    tool_call_count: int = 1,
) -> EvalCaseResult:
    return EvalCaseResult(
        case_id="c",
        query="q",
        category="factual",
        should_call_tool=should_call_tool,
        tool_called=tool_called,
        primary_intent_match=primary_intent_match,
        primary_strategy_match=primary_strategy_match,
        router_intent_match=router_intent_expected,
        router_strategy_match=router_strategy_expected,
        router_fallback_used=router_fallback,
        query_rewrite_drift=drift,
        critical_term_preservation_rate=preservation_rate,
        source_recall=source_recall_val,
        citation_grounded=grounded,
        citation_source_recall=source_recall_val,
        answer_terms_all_present=term_ok,
        latency_ms=latency_ms,
        expect_abstain=expect_abstain,
        abstained=abstained,
        input_tokens=tokens[0] if tokens else None,
        output_tokens=tokens[1] if tokens else None,
        total_tokens=tokens[2] if tokens else None,
        model_calls=model_calls,
        tool_call_count=tool_call_count,
        failure_category=failure_category,
    )


def test_compute_metrics_aggregates() -> None:
    results = [
        _case_result(tool_called=True, source_recall_val=1.0),
        _case_result(tool_called=True, source_recall_val=0.5),
    ]
    m = compute_metrics(results)
    assert m.sample_count == 2
    assert m.tool_selection_accuracy == 1.0
    assert m.primary_intent_accuracy == 1.0
    assert m.primary_strategy_accuracy == 1.0
    assert m.routing_fallback_rate == 0.0
    assert m.expected_source_recall == 0.75
    assert m.citation_grounded_rate == 1.0
    assert m.answer_term_match_rate == 1.0
    assert m.latency_p50_ms == 100.0
    assert m.total_tokens == 60
    assert m.tokens_per_case == 30.0
    assert m.model_calls_per_case == 2.0
    assert m.tool_calls_per_case == 1.0
    assert m.failure_counts == {}
    assert m.failed_case_ids == []


def test_compute_metrics_layered_routing() -> None:
    """Layer B vs Layer C are aggregated independently (Stage 5.1, §3/§7)."""
    results = [
        #: Layer B right, Layer C wrong -> only Layer B counts a hit
        _case_result(
            tool_called=True,
            primary_intent_match=False,
            primary_strategy_match=False,
            router_intent_expected=True,
            router_strategy_expected=True,
            drift=True,
            preservation_rate=0.0,
            failure_category=FailureCategory.QUERY_REWRITE_INTENT_DRIFT,
        ),
        _case_result(
            tool_called=True,
            router_intent_expected=True,
            router_strategy_expected=True,
            preservation_rate=1.0,
        ),
    ]
    m = compute_metrics(results)
    assert m.router_component_intent_accuracy == 1.0
    assert m.router_component_strategy_accuracy == 1.0
    assert m.primary_intent_accuracy == 0.5
    assert m.primary_strategy_accuracy == 0.5
    assert m.query_rewrite_drift_count == 1
    assert m.critical_term_preservation_rate == 0.5
    #: NO falls into query-rewrite drift is a diagnostic, not a failed case.
    assert "QUERY_REWRITE_INTENT_DRIFT" in m.failure_counts
    assert m.failed_case_ids == []


def test_compute_metrics_router_fallback_aggregated() -> None:
    m = compute_metrics([_case_result(tool_called=True, router_fallback=True)])
    assert m.router_component_fallback_rate == 1.0


def test_compute_metrics_empty() -> None:
    m = compute_metrics([])
    assert m.sample_count == 0
    assert m.tool_selection_accuracy is None


def test_round_trip_primary_intent_strategy() -> None:
    #: pure model-level sanity: enums survive serialization
    case = EvalCaseResult(
        case_id="r1",
        query="q",
        category="relationship",
        should_call_tool=True,
        tool_called=True,
        expected_intent=RetrievalIntent.RELATIONAL,
        primary_intent=RetrievalIntent.RELATIONAL,
        expected_strategy=RetrievalStrategy.HYBRID,
        primary_strategy=RetrievalStrategy.HYBRID,
    )
    restored = EvalCaseResult.model_validate_json(case.model_dump_json())
    assert restored.expected_intent is RetrievalIntent.RELATIONAL
    assert restored.primary_intent is RetrievalIntent.RELATIONAL
    assert restored.expected_strategy is RetrievalStrategy.HYBRID
    assert restored.primary_strategy is RetrievalStrategy.HYBRID


def test_router_component_metrics() -> None:
    results = [
        RouterComponentResult(
            case_id="a",
            query="q1",
            expected_intent=RetrievalIntent.FACTUAL,
            actual_intent=RetrievalIntent.FACTUAL,
            expected_strategy=RetrievalStrategy.FOCUSED,
            actual_strategy=RetrievalStrategy.FOCUSED,
            intent_match=True,
            strategy_match=True,
            fallback_used=False,
        ),
        RouterComponentResult(
            case_id="b",
            query="q2",
            expected_intent=RetrievalIntent.OVERVIEW,
            actual_intent=RetrievalIntent.FACTUAL,
            expected_strategy=RetrievalStrategy.GLOBAL,
            actual_strategy=RetrievalStrategy.FOCUSED,
            intent_match=False,
            strategy_match=False,
            fallback_used=True,
        ),
    ]
    summary = router_component_metrics(results)
    assert summary.intent_accuracy == 0.5
    assert summary.strategy_accuracy == 0.5
    assert summary.fallback_rate == 0.5

    assert router_component_metrics([]).intent_accuracy is None
