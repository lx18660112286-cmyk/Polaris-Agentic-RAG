"""Offline tests for the regression gate (spec §31-§34).

The flywheel records a decision; it never auto-applies anything. Tests
verify ``compute_deltas`` and that the hard gates (citation groundedness,
abstention, zero system failures) drive REJECT vs HUMAN_REVIEW.
"""

from __future__ import annotations

from polaris_agentic_rag.evaluation.models import MetricSummary
from polaris_agentic_rag.flywheel.regression import RegressionGate, compute_deltas


def _summary(**kw) -> MetricSummary:
    base: dict = {}
    base.update(kw)
    return MetricSummary(**base)


def test_compute_deltas_candidate_minus_baseline() -> None:
    base = _summary(citation_grounded_rate=0.9, abstention_accuracy=0.8)
    cand = _summary(citation_grounded_rate=0.95, abstention_accuracy=0.85)
    deltas = compute_deltas(base, cand)
    assert deltas["citation_grounded_rate"] == 0.05
    assert deltas["abstention_accuracy"] == 0.05


def test_compute_deltas_skips_missing_metrics() -> None:
    deltas = compute_deltas(_summary(), _summary())
    assert deltas == {}


def test_gate_all_good_recommends_human_review() -> None:
    gate = RegressionGate()
    base = _summary(
        citation_grounded_rate=1.0,
        abstention_accuracy=1.0,
        failure_counts={"NO_EVIDENCE": 2},
    )
    cand = _summary(
        citation_grounded_rate=1.0,
        abstention_accuracy=1.0,
        failure_counts={"NO_EVIDENCE": 2},
    )
    result = gate.check("p1", baseline=base, candidate=cand, tests_passed=True)
    assert result.hard_gate_ok is True
    assert result.hard_gate_violations == []
    assert result.decision == "HUMAN_REVIEW"


def test_gate_rejects_when_tests_fail() -> None:
    gate = RegressionGate()
    base = _summary(citation_grounded_rate=1.0)
    cand = _summary(citation_grounded_rate=1.0)
    result = gate.check("p1", baseline=base, candidate=cand, tests_passed=False)
    assert result.decision == "REJECT"


def test_gate_rejects_on_citation_regression() -> None:
    gate = RegressionGate()
    base = _summary(citation_grounded_rate=0.95)
    cand = _summary(citation_grounded_rate=0.9)  # -5pp, beyond 1pp tolerance
    result = gate.check("p1", baseline=base, candidate=cand, tests_passed=True)
    assert result.hard_gate_ok is False
    assert any("citation" in v for v in result.hard_gate_violations)
    assert result.decision == "REJECT"


def test_gate_allows_negligible_citation_tolerance() -> None:
    gate = RegressionGate()
    base = _summary(citation_grounded_rate=0.95)
    cand = _summary(citation_grounded_rate=0.945)  # within 1pp tolerance
    result = gate.check("p1", baseline=base, candidate=cand, tests_passed=True)
    assert result.hard_gate_ok is True
    assert result.decision == "HUMAN_REVIEW"


def test_gate_rejects_on_abstention_regression() -> None:
    gate = RegressionGate()
    base = _summary(abstention_accuracy=0.9)
    cand = _summary(abstention_accuracy=0.8)
    result = gate.check("p1", baseline=base, candidate=cand, tests_passed=True)
    assert result.decision == "REJECT"


def test_gate_rejects_on_system_failures() -> None:
    gate = RegressionGate()
    base = _summary(citation_grounded_rate=1.0, failure_counts={})
    cand = _summary(citation_grounded_rate=1.0, failure_counts={"TOOL_ERROR": 1})
    result = gate.check("p1", baseline=base, candidate=cand, tests_passed=True)
    assert result.hard_gate_ok is False
    assert any("system failure" in v for v in result.hard_gate_violations)
    assert result.decision == "REJECT"


def test_gate_ignores_business_outcomes_as_failures() -> None:
    gate = RegressionGate()
    #: NO_EVIDENCE is an honest abstention, not a system failure.
    cand = _summary(citation_grounded_rate=1.0, failure_counts={"NO_EVIDENCE": 3})
    base = _summary(citation_grounded_rate=1.0)
    result = gate.check("p1", baseline=base, candidate=cand, tests_passed=True)
    assert result.hard_gate_ok is True


def test_gate_records_deltas_and_metrics() -> None:
    gate = RegressionGate()
    base = _summary(citation_grounded_rate=0.9, tool_selection_accuracy=0.97)
    cand = _summary(citation_grounded_rate=0.93, tool_selection_accuracy=0.97)
    result = gate.check("p1", baseline=base, candidate=cand, tests_passed=True)
    assert result.deltas["citation_grounded_rate"] == 0.03
    assert result.baseline_metrics["citation_grounded_rate"] == 0.9
    assert result.candidate_metrics["citation_grounded_rate"] == 0.93
