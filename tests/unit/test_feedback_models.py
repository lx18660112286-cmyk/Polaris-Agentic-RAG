"""Offline tests for the flywheel domain models (spec §4-§12, §14).

Deterministic only: no LLM, no LightRAG. Verifies enums + simple
predicates such as ``is_negative_feedback`` and the FeedbackEvent /
ReviewCandidate / ImprovementProposal / EvalCandidate contracts.
"""

from __future__ import annotations

from polaris_agentic_rag.flywheel.models import (
    EvalCandidate,
    EvalPromotionStatus,
    FeedbackEvent,
    FeedbackType,
    FlywheelMetrics,
    ImprovementCategory,
    ImprovementProposal,
    ProposalStatus,
    ProposalType,
    ReviewCandidate,
    ReviewPriority,
    ReviewSource,
    ReviewStatus,
    is_negative_feedback,
)
from polaris_agentic_rag.retrieval.models import RetrievalIntent, RetrievalStrategy


def test_feedback_type_membership() -> None:
    assert FeedbackType.POSITIVE.value == "POSITIVE"
    assert len(FeedbackType) == 9


def test_is_negative_feedback() -> None:
    #: POSITIVE is the only non-negative type.
    assert not is_negative_feedback(FeedbackType.POSITIVE)
    for t in (
        FeedbackType.INCORRECT,
        FeedbackType.INCOMPLETE,
        FeedbackType.UNSUPPORTED,
        FeedbackType.IRRELEVANT,
        FeedbackType.SHOULD_HAVE_RETRIEVED,
        FeedbackType.SHOULD_NOT_HAVE_RETRIEVED,
        FeedbackType.BAD_CITATION,
        FeedbackType.OTHER,
    ):
        assert is_negative_feedback(t)


def test_feedback_event_defaults() -> None:
    event = FeedbackEvent(
        feedback_id="fb1", trace_id="t1", query="q", feedback_type=FeedbackType.POSITIVE
    )
    assert event.answer == ""
    assert event.comment is None
    assert event.citations == []
    assert event.created_at == ""


def test_review_candidate_default_status_pending() -> None:
    cand = ReviewCandidate(
        candidate_id="c1",
        trace_id="t1",
        source=ReviewSource.RUNTIME_SIGNAL,
        reason="r",
        priority=ReviewPriority.MEDIUM,
    )
    assert cand.status is ReviewStatus.PENDING
    assert cand.category is None
    assert cand.failure_layer is None
    assert cand.tool_queries == []


def test_improvement_proposal_provenance_defaults() -> None:
    prop = ImprovementProposal(
        proposal_id="p1",
        category=ImprovementCategory.KNOWLEDGE_GAP,
        proposal_type=ProposalType.ADD_EVAL_CASE,
    )
    assert prop.status is ProposalStatus.OPEN
    assert prop.source_candidate_ids == []
    assert prop.evidence == {}


def test_eval_candidate_holds_labels_and_provenance() -> None:
    cand = EvalCandidate(
        candidate_id="e1",
        query="what does the term mean",
        category="terminology",
        should_retrieve=True,
        expected_intent=RetrievalIntent.TERMINOLOGY,
        expected_strategy=RetrievalStrategy.FOCUSED,
        proposal_id="p1",
        source_candidate_id="c1",
        feedback_id="fb1",
        trace_id="t1",
    )
    assert cand.status is EvalPromotionStatus.PENDING
    assert cand.expected_intent is RetrievalIntent.TERMINOLOGY
    assert cand.proposal_id == "p1"


def test_flywheel_metrics_all_zero_no_fabricated_rates() -> None:
    m = FlywheelMetrics()
    assert m.feedback_count == 0
    assert m.feedback_to_eval_conversion_rate is None
    assert m.knowledge_gap_rate is None
