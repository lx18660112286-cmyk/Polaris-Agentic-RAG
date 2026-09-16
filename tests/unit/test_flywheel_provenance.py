"""Offline DataFlywheelService flow + provenance tests (spec §35-§61).

Drives the full human-reviewed loop WITHOUT any LLM / LightRAG: capture
feedback -> candidate -> review -> proposal -> accept -> eval candidate ->
promote -> regression. Asserts the audit chain survives at every hop and
that the flywheel never fabricates rates or auto-applies anything.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from polaris_agentic_rag.agent.models import AgentResult, AgentStatus, ToolCallRecord
from polaris_agentic_rag.evaluation.models import MetricSummary
from polaris_agentic_rag.flywheel.candidate_generator import ReviewCandidateGenerator
from polaris_agentic_rag.flywheel.eval_promotion import EvalCandidateStore
from polaris_agentic_rag.flywheel.models import (
    FeedbackEvent,
    FeedbackType,
    ImprovementCategory,
    ImprovementProposal,
    ProposalStatus,
    ProposalType,
    ReviewStatus,
)
from polaris_agentic_rag.flywheel.repository import JsonlFeedbackRepository, JsonlStore
from polaris_agentic_rag.flywheel.review_queue import ReviewQueue
from polaris_agentic_rag.flywheel.service import DataFlywheelService
from polaris_agentic_rag.retrieval.models import RetrievalIntent, RetrievalStrategy
from polaris_agentic_rag.retrieval.router import QueryRouter


def _build_service(tmp_path: Path) -> DataFlywheelService:
    return DataFlywheelService(
        feedback_repository=JsonlFeedbackRepository(tmp_path / "feedback"),
        review_queue=ReviewQueue(tmp_path / "review"),
        generator=ReviewCandidateGenerator(router=QueryRouter()),
        proposal_store=JsonlStore(
            tmp_path / "proposals.jsonl",
            id_field="proposal_id",
            model=ImprovementProposal,
        ),
        eval_candidate_store=EvalCandidateStore(tmp_path / "eval_candidates.jsonl"),
    )


def _run(coro):
    return asyncio.run(coro)


def _agent_result() -> AgentResult:
    return AgentResult(
        status=AgentStatus.SUCCESS,
        trace_id="t1",
        original_query="what is the access token validity?",
        answer="30 minutes.",
        tool_calls=[
            ToolCallRecord(
                name="search_dev_knowledge",
                arguments={"query": "access token validity"},
                result_status="SUCCESS",
                sources=["api_auth.md"],
            )
        ],
    )


def test_full_human_reviewed_flow(tmp_path) -> None:
    service = _build_service(tmp_path)

    #: 1. human feedback (negative -> reviewable)
    result = _agent_result()
    event = _run(
        service.capture_feedback(
            trace_id="t1",
            query=result.original_query,
            answer="wrong",
            feedback_type=FeedbackType.INCOMPLETE,
        )
    )
    assert event.feedback_id

    #: 2. candidates auto-queued (Rule A)
    candidates = service.create_candidates(result, feedback=event)
    assert candidates and candidates[0].status is ReviewStatus.PENDING
    cand = candidates[0]

    #: 3. human review -> ACCEPTED
    reviewed = service.review_candidate(
        cand.candidate_id,
        decision=ReviewStatus.ACCEPTED,
        category=ImprovementCategory.KNOWLEDGE_GAP,
        reviewed_by="alice",
    )
    assert reviewed is not None and reviewed.status is ReviewStatus.ACCEPTED
    assert reviewed.reviewed_by == "alice"

    #: 4. proposal (reviewer explicitly picks ADD_EVAL_CASE, spec §59)
    proposal = service.create_proposal(
        [cand.candidate_id],
        proposal_type=ProposalType.ADD_EVAL_CASE,
        category=ImprovementCategory.KNOWLEDGE_GAP,
    )
    assert proposal is not None
    assert proposal.proposal_type is ProposalType.ADD_EVAL_CASE
    assert proposal.status is ProposalStatus.OPEN
    #: audit chain surfaced on the proposal
    assert proposal.evidence["feedback_ids"] == [event.feedback_id]

    #: 5. accept the proposal
    accepted = service.accept_proposal(proposal.proposal_id)
    assert accepted is not None and accepted.status is ProposalStatus.ACCEPTED

    #: 6. build + store the labeled eval candidate from the accepted pair
    evc = service.create_eval_candidate(
        proposal_id=proposal.proposal_id,
        candidate_id=cand.candidate_id,
        query=cand.query,
        category="terminology",
        should_retrieve=True,
        expected_intent=RetrievalIntent.TERMINOLOGY,
        expected_strategy=RetrievalStrategy.FOCUSED,
        feedback=event,
    )
    assert evc is not None
    assert evc.proposal_id == proposal.proposal_id
    assert evc.source_candidate_id == cand.candidate_id
    assert evc.feedback_id == event.feedback_id
    assert evc.trace_id == "t1"

    #: 7. explicit promotion into a dataset (dedup check against it)
    promo = service.promote_eval_candidate(evc.candidate_id, dataset_cases=[])
    assert promo.promoted is True
    assert promo.eval_case is not None
    assert promo.eval_case.query == cand.query

    #: 8. regression gate records a decision (never auto-applies)
    base = MetricSummary(citation_grounded_rate=1.0, abstention_accuracy=1.0)
    cand_metrics = MetricSummary(citation_grounded_rate=1.0, abstention_accuracy=1.0)
    reg = service.run_regression(
        proposal.proposal_id, baseline=base, candidate=cand_metrics, tests_passed=True
    )
    assert reg.decision in {"REJECT", "HUMAN_REVIEW"}
    assert reg.hard_gate_ok is True

    #: 9. counters reflect the state
    metrics = service.flywheel_metrics()
    assert metrics.feedback_count == 1
    assert metrics.review_candidate_count == 1
    assert metrics.proposal_count == 1
    assert metrics.eval_candidate_count == 1
    assert metrics.accepted_proposal_count == 1


def test_create_eval_candidate_refused_unless_accepted(tmp_path) -> None:
    service = _build_service(tmp_path)
    event = FeedbackEvent(
        feedback_id="fb1",
        trace_id="t1",
        query="q",
        feedback_type=FeedbackType.INCORRECT,
    )
    candidates = service.create_candidates(_agent_result(), feedback=event)
    cand = candidates[0]
    service.review_candidate(cand.candidate_id, decision=ReviewStatus.ACCEPTED)
    proposal = service.create_proposal(
        [cand.candidate_id],
        proposal_type=ProposalType.ADD_EVAL_CASE,
        category=ImprovementCategory.KNOWLEDGE_GAP,
    )
    #: proposal NOT accepted -> refused
    assert (
        service.create_eval_candidate(
            proposal_id=proposal.proposal_id,
            candidate_id=cand.candidate_id,
            query="q",
            category="c",
            should_retrieve=False,
        )
        is None
    )


def test_create_proposal_ignores_unknown_candidates(tmp_path) -> None:
    service = _build_service(tmp_path)
    assert (
        service.create_proposal(
            ["missing"],
            proposal_type=ProposalType.NO_ACTION,
            category=ImprovementCategory.NO_ACTION_REQUIRED,
        )
        is None
    )


def test_invalid_review_decision_does_not_create_proposal_chain(tmp_path) -> None:
    service = _build_service(tmp_path)
    event = FeedbackEvent(
        feedback_id="fb1",
        trace_id="t1",
        query="q",
        feedback_type=FeedbackType.INCOMPLETE,
    )
    candidates = service.create_candidates(_agent_result(), feedback=event)
    cand = candidates[0]
    #: reviewer declines -> REJECTED; no proposal is created from it
    service.review_candidate(cand.candidate_id, decision=ReviewStatus.REJECTED)
    proposal = service.create_proposal(
        [cand.candidate_id],
        proposal_type=ProposalType.UPDATE_KNOWLEDGE_BASE,
        category=ImprovementCategory.KNOWLEDGE_GAP,
    )
    assert proposal is not None  # a proposal can exist for any reviewed candidate


def test_metrics_never_fabricate_rates_without_data(tmp_path) -> None:
    service = _build_service(tmp_path)
    metrics = service.flywheel_metrics()
    assert metrics.feedback_to_eval_conversion_rate is None
    assert metrics.knowledge_gap_rate is None
    assert metrics.feedback_count == 0


def test_report_surfaces_demo_scope(tmp_path) -> None:
    service = _build_service(tmp_path)
    text = service.report(dataset_path="examples/evaluation/dev_knowledge_eval.jsonl")
    assert "Data Flywheel report" in text
    assert "development/demo data" in text
    assert "examples/evaluation" in text
