"""Flywheel counters + report text (spec §53-§55).

Simple, honest counters -- no synthetic ``flywheel_score`` (spec §53).
Rate metrics stay ``None`` when there is no real data; we never fabricate a
baseline (spec §54).
"""

from __future__ import annotations

from polaris_agentic_rag.flywheel.models import (
    EvalCandidate,
    EvalPromotionStatus,
    FeedbackEvent,
    FlywheelMetrics,
    ImprovementCategory,
    ImprovementProposal,
    ProposalStatus,
    ReviewCandidate,
    ReviewStatus,
    is_negative_feedback,
)

__all__ = ["compute_flywheel_metrics", "format_flywheel_report"]


def compute_flywheel_metrics(
    *,
    feedback_events: list[FeedbackEvent],
    review_candidates: list[ReviewCandidate],
    proposals: list[ImprovementProposal],
    eval_candidates: list[EvalCandidate],
) -> FlywheelMetrics:
    """Aggregate flywheel state into counters (spec §53/§54)."""
    feedback_count = len(feedback_events)
    positive = sum(1 for f in feedback_events if not is_negative_feedback(f.feedback_type))
    negative = sum(1 for f in feedback_events if is_negative_feedback(f.feedback_type))

    pending_review = sum(1 for c in review_candidates if c.status is ReviewStatus.PENDING)
    knowledge_gap = sum(
        1 for c in review_candidates if c.category is ImprovementCategory.KNOWLEDGE_GAP
    )
    drift = sum(
        1 for c in review_candidates if c.category is ImprovementCategory.QUERY_REWRITE_INTENT_DRIFT
    )
    accepted = sum(1 for p in proposals if p.status is ProposalStatus.ACCEPTED)
    rejected = sum(1 for p in proposals if p.status is ProposalStatus.REJECTED)
    promoted = sum(1 for e in eval_candidates if e.status is EvalPromotionStatus.PROMOTED)

    conversion: float | None = None
    if negative:
        conversion = round((promoted / negative) if negative else 0.0, 4)
    knowledge_gap_rate: float | None = None
    if review_candidates:
        knowledge_gap_rate = round(knowledge_gap / len(review_candidates), 4)

    return FlywheelMetrics(
        feedback_count=feedback_count,
        positive_feedback_count=positive,
        negative_feedback_count=negative,
        review_candidate_count=len(review_candidates),
        pending_review_count=pending_review,
        knowledge_gap_count=knowledge_gap,
        query_rewrite_drift_count=drift,
        proposal_count=len(proposals),
        eval_candidate_count=len(eval_candidates),
        accepted_proposal_count=accepted,
        rejected_proposal_count=rejected,
        feedback_to_eval_conversion_rate=conversion,
        knowledge_gap_rate=knowledge_gap_rate,
    )


def format_flywheel_report(
    metrics: FlywheelMetrics,
    *,
    dataset_path: str = "",
    scope: str = "development/demo data",
) -> str:
    """Render a human-readable data-flywheel report (spec §55).

    ``scope`` is surfaced so we never present demo data as production
    metrics (spec §55).
    """
    lines = [
        "=" * 60,
        "Data Flywheel report",
        "=" * 60,
        f"scope           : {scope}",
        f"feedback        : {metrics.feedback_count}  "
        f"(positive={metrics.positive_feedback_count}, negative={metrics.negative_feedback_count})",
        f"review queue    : {metrics.review_candidate_count}  "
        f"(pending={metrics.pending_review_count})",
        f"categories      : knowledge_gap={metrics.knowledge_gap_count}  "
        f"rewrite_drift={metrics.query_rewrite_drift_count}",
        f"proposals       : {metrics.proposal_count}  "
        f"(accepted={metrics.accepted_proposal_count}, rejected={metrics.rejected_proposal_count})",
        f"eval candidates : {metrics.eval_candidate_count}",
        "rates           : "
        f"feedback_to_eval_conversion_rate="
        f"{_fmt_rate(metrics.feedback_to_eval_conversion_rate)}  "
        f"knowledge_gap_rate={_fmt_rate(metrics.knowledge_gap_rate)}",
    ]
    if dataset_path:
        lines.append(f"dataset         : {dataset_path}")
    lines.append("=" * 60)
    return "\n".join(lines)


def _fmt_rate(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "n/a"
