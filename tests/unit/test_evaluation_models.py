"""Offline tests for EvalCase / EvalCaseResult / EvalRunResult models (spec §21)."""

from __future__ import annotations

from dev_knowledge_agent.evaluation.models import (
    EvalCase,
    EvalCaseResult,
    EvalRunResult,
    MetricSummary,
)
from dev_knowledge_agent.retrieval.models import RetrievalIntent, RetrievalStrategy


def test_eval_case_round_trip_json() -> None:
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
    restored = EvalCase.model_validate_json(case.model_dump_json())
    assert restored == case
    assert restored.expected_intent is RetrievalIntent.FACTUAL
    assert restored.expected_strategy is RetrievalStrategy.FOCUSED


def test_eval_case_defaults() -> None:
    case = EvalCase(id="d1", query="你好", category="direct_answer")
    assert case.should_call_tool is False
    assert case.expected_intent is None
    assert case.expected_sources == []
    assert case.expected_answer_terms == []
    assert case.expect_abstain is False


def test_eval_case_result_encodes_actuals() -> None:
    result = EvalCaseResult(
        case_id="f1",
        query="q",
        category="factual",
        should_call_tool=True,
        tool_called=True,
        actual_intent=RetrievalIntent.FACTUAL,
        tool_selection_correct=True,
    )
    assert result.tool_selection_correct is True
    assert result.actual_intent is RetrievalIntent.FACTUAL


def test_eval_run_result_aggregates_cases_and_metrics() -> None:
    run = EvalRunResult(
        dataset="dev_knowledge_eval",
        run_at="2026-09-15T00:00:00+00:00",
        sample_count=2,
        cases=[
            EvalCaseResult(case_id="a", query="a", category="x", should_call_tool=True),
            EvalCaseResult(case_id="b", query="b", category="x", should_call_tool=False),
        ],
        metrics=MetricSummary(sample_count=2, tool_selection_accuracy=1.0),
    )
    assert len(run.cases) == 2
    assert run.metrics.sample_count == 2
    assert run.metrics.tool_selection_accuracy == 1.0


def test_metric_summary_defaults_are_safe() -> None:
    m = MetricSummary()
    assert m.sample_count == 0
    assert m.failure_counts == {}
    assert m.failed_case_ids == []
    assert m.tool_selection_accuracy is None
