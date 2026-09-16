"""Regression gate for proposals (spec §31-§34).

Guards the decision to apply an improvement by comparing a candidate
metric summary against the baseline. LLM-backed evaluation has sampling
noise, so we do NOT require "every metric >= previous" (spec §33). We set
strong hard constraints and record everything else as deltas for a human:

    * Citation Groundedness must not materially regress
    * Abstention must not materially regress
    * System Failures must remain zero

The deterministic offline tests (pytest -m 'not integration', ruff, mypy)
are a separate hard gate that a caller runs outside this module; we record
whether they passed (spec §34). The flywheel only *records*; it never
auto-applies a proposal (spec §35).
"""

from __future__ import annotations

from polaris_agentic_rag.evaluation.models import MetricSummary
from polaris_agentic_rag.flywheel.models import RegressionCheckResult
from polaris_agentic_rag.observability.models import FailureCategory

__all__ = ["RegressionGate", "compute_deltas"]

#: Business/diagnostic outcomes that are NOT "system failures" (spec §33):
#: NO_EVIDENCE is an honest abstention, query-rewrite drift is a soft signal.
_BUSINESS_CATEGORIES = frozenset(
    {
        FailureCategory.NO_EVIDENCE.value,
        FailureCategory.QUERY_REWRITE_INTENT_DRIFT.value,
        FailureCategory.EVALUATION_AGGREGATION_ERROR.value,
    }
)


def compute_deltas(
    baseline: MetricSummary,
    candidate: MetricSummary,
) -> dict[str, float]:
    """Per-metric candidate-minus-baseline deltas for the summary (spec §31).

    Yields the deltas as ``(metric_label, delta_percentage_points)``. Labels
    are the durable metric names used in both summaries.
    """
    keys = (
        "tool_selection_accuracy",
        "router_component_intent_accuracy",
        "router_component_strategy_accuracy",
        "primary_intent_accuracy",
        "primary_strategy_accuracy",
        "expected_source_recall",
        "citation_grounded_rate",
        "abstention_accuracy",
        "answer_term_match_rate",
    )
    deltas: dict[str, float] = {}
    for key in keys:
        base = getattr(baseline, key, None)
        cand = getattr(candidate, key, None)
        if base is None or cand is None:
            continue
        deltas[key] = round((cand or 0.0) - (base or 0.0), 4)
    return deltas


def _system_failure_count(metrics: MetricSummary) -> int:
    """Count hard/system failures, excluding business/diagnostic outcomes."""
    return sum(
        count
        for category, count in metrics.failure_counts.items()
        if category not in _BUSINESS_CATEGORIES
    )


class RegressionGate:
    """Evaluate one proposal against baseline + candidate metrics (spec §32/§33)."""

    def __init__(self, *, hard_tolerance: float = 0.01) -> None:
        self._hard_tolerance = hard_tolerance

    def check(
        self,
        proposal_id: str,
        *,
        baseline: MetricSummary,
        candidate: MetricSummary,
        tests_passed: bool,
    ) -> RegressionCheckResult:
        """Return the regression check result + recommended decision.

        Decision: ``REJECT`` when a hard gate fails or the deterministic
        tests did not pass; ``HUMAN_REVIEW`` otherwise (a human inspects the
        recorded deltas before any apply -- spec §33).
        """
        deltas = compute_deltas(baseline, candidate)
        violations: list[str] = []

        base_citation = baseline.citation_grounded_rate
        cand_citation = candidate.citation_grounded_rate
        if (
            base_citation is not None
            and cand_citation is not None
            and cand_citation < base_citation - self._hard_tolerance
        ):
            violations.append(
                f"citation_grounded_rate regressed {base_citation:.3f} -> {cand_citation:.3f}"
            )

        base_abstain = baseline.abstention_accuracy
        cand_abstain = candidate.abstention_accuracy
        if (
            base_abstain is not None
            and cand_abstain is not None
            and cand_abstain < base_abstain - self._hard_tolerance
        ):
            violations.append(
                f"abstention_accuracy regressed {base_abstain:.3f} -> {cand_abstain:.3f}"
            )

        cand_failures = _system_failure_count(candidate)
        if cand_failures > 0:
            violations.append(f"system failure count is {cand_failures} (must remain zero)")

        hard_gate_ok = not violations
        decision = "REJECT" if not tests_passed or not hard_gate_ok else "HUMAN_REVIEW"

        return RegressionCheckResult(
            proposal_id=proposal_id,
            baseline_metrics=_flat(baseline),
            candidate_metrics=_flat(candidate),
            deltas=deltas,
            hard_gate_ok=hard_gate_ok,
            hard_gate_violations=violations,
            tests_passed=tests_passed,
            decision=decision,
        )


def _flat(metrics: MetricSummary) -> dict[str, float]:
    """Flatten the few gate-relevant metrics to a comparable dict."""
    return {
        key: float(value)
        for key in (
            "tool_selection_accuracy",
            "router_component_intent_accuracy",
            "router_component_strategy_accuracy",
            "primary_intent_accuracy",
            "primary_strategy_accuracy",
            "expected_source_recall",
            "citation_grounded_rate",
            "abstention_accuracy",
            "answer_term_match_rate",
        )
        if (value := getattr(metrics, key, None)) is not None
    }
