"""Offline tests for the failure taxonomy mapping (spec §32/§50)."""

from __future__ import annotations

from dev_knowledge_agent.agent.models import AgentResult, AgentStatus, ToolCallRecord
from dev_knowledge_agent.evaluation.metrics import classify_failure
from dev_knowledge_agent.observability.models import FailureCategory


def test_no_failure_for_success() -> None:
    result = AgentResult(status=AgentStatus.SUCCESS, answer="ok")
    assert classify_failure(result) is None


def test_model_error_mapped() -> None:
    result = AgentResult(status=AgentStatus.MODEL_ERROR, error="boom: rate limit")
    assert classify_failure(result) is FailureCategory.MODEL_ERROR


def test_max_steps_mapped() -> None:
    result = AgentResult(status=AgentStatus.MAX_STEPS_EXCEEDED)
    assert classify_failure(result) is FailureCategory.MAX_STEPS


def test_max_tool_calls_mapped() -> None:
    result = AgentResult(
        status=AgentStatus.TOOL_ERROR,
        error="Agent exceeded max_tool_calls=3",
    )
    assert classify_failure(result) is FailureCategory.MAX_TOOL_CALLS


def test_unknown_tool_mapped_from_record() -> None:
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        tool_calls=[ToolCallRecord(name="x", arguments={}, result_status="unknown_tool")],
    )
    assert classify_failure(result) is FailureCategory.UNKNOWN_TOOL


def test_invalid_arguments_mapped_from_record() -> None:
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        tool_calls=[ToolCallRecord(name="x", arguments={}, result_status="invalid_arguments")],
    )
    assert classify_failure(result) is FailureCategory.INVALID_TOOL_ARGUMENTS


def test_no_evidence_is_a_business_outcome_not_a_hard_error() -> None:
    result = AgentResult(
        status=AgentStatus.SUCCESS,
        tool_calls=[ToolCallRecord(name="x", arguments={}, result_status="NO_EVIDENCE")],
    )
    assert classify_failure(result) is FailureCategory.NO_EVIDENCE


def test_hard_error_wins_over_no_evidence() -> None:
    result = AgentResult(
        status=AgentStatus.MODEL_ERROR,
        error="provider 429",
        tool_calls=[ToolCallRecord(name="x", arguments={}, result_status="NO_EVIDENCE")],
    )
    assert classify_failure(result) is FailureCategory.MODEL_ERROR
    assert classify_failure(result) is not FailureCategory.NO_EVIDENCE


def test_failure_categories_cover_the_taxonomy() -> None:
    expected = {
        "MODEL_ERROR",
        "TOOL_ERROR",
        "INVALID_TOOL_ARGUMENTS",
        "UNKNOWN_TOOL",
        "MAX_STEPS",
        "MAX_TOOL_CALLS",
        "NO_EVIDENCE",
        "ROUTING_FALLBACK",
        "RETRIEVAL_ERROR",
        "CITATION_ERROR",
        #: Stage 5.1 diagnostics (spec §19/§32)
        "QUERY_REWRITE_INTENT_DRIFT",
        "EVALUATION_AGGREGATION_ERROR",
    }
    actual = {c.value for c in FailureCategory}
    assert expected == actual
