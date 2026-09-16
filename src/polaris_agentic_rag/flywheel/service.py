"""DataFlywheelService -- coordination root of the data flywheel (spec §35).

Responsibilities (spec §35): ``capture_feedback``, ``create_candidate``,
``review_candidate``, ``create_proposal``, ``create_eval_candidate``,
``run_regression``.

Hard rule (spec §35): the service orchestrates data state transitions only.
It NEVER modifies the router, the prompt, or the knowledge base. Knowledge
updates must come from a human-authored / trusted source, never computed
here (spec §28/§75).
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from polaris_agentic_rag.agent.models import AgentResult
from polaris_agentic_rag.evaluation.models import EvalCase, MetricSummary
from polaris_agentic_rag.flywheel.candidate_generator import ReviewCandidateGenerator
from polaris_agentic_rag.flywheel.eval_promotion import (
    EvalCandidateStore,
    PromotionResult,
    build_eval_candidate,
)
from polaris_agentic_rag.flywheel.ids import make_id, utc_now_iso
from polaris_agentic_rag.flywheel.metrics import (
    compute_flywheel_metrics,
    format_flywheel_report,
)
from polaris_agentic_rag.flywheel.models import (
    EvalCandidate,
    FeedbackEvent,
    FeedbackType,
    FlywheelMetrics,
    ImprovementCategory,
    ImprovementProposal,
    ProposalStatus,
    ProposalType,
    RegressionCheckResult,
    ReviewCandidate,
    ReviewStatus,
)
from polaris_agentic_rag.flywheel.proposals import build_proposal, suggest_proposal_type
from polaris_agentic_rag.flywheel.regression import RegressionGate
from polaris_agentic_rag.flywheel.repository import FeedbackRepository, JsonlStore
from polaris_agentic_rag.flywheel.review_queue import ReviewQueue
from polaris_agentic_rag.observability.models import TraceEvent

__all__ = [
    "DataFlywheelService",
    "flywheel_links",
]


def flywheel_links(
    *,
    feedback_dir: str | Path = ".local/feedback",
    review_dir: str | Path = ".local/review",
    proposals_dir: str | Path = ".local/flywheel",
    eval_candidates_dir: str | Path = ".local/flywheel",
) -> dict[str, Path]:
    """Resolve the gitignored flywheel storage paths (spec §8/§16/§23)."""
    return {
        "feedback": Path(feedback_dir) / "feedback.jsonl",
        "review": Path(review_dir) / "review.jsonl",
        "proposals": Path(proposals_dir) / "proposals.jsonl",
        "eval_candidates": Path(eval_candidates_dir) / "eval_candidates.jsonl",
    }


class DataFlywheelService:
    """Compose feedback capture, review, proposal, eval-candidate and regression."""

    def __init__(
        self,
        *,
        feedback_repository: FeedbackRepository,
        review_queue: ReviewQueue,
        generator: ReviewCandidateGenerator,
        proposal_store: JsonlStore | None = None,
        eval_candidate_store: EvalCandidateStore | None = None,
        regression_gate: RegressionGate | None = None,
    ) -> None:
        self._feedback = feedback_repository
        self._queue = review_queue
        self._generator = generator
        self._proposals = proposal_store or JsonlStore(
            Path(".local/flywheel/proposals.jsonl"),
            id_field="proposal_id",
            model=ImprovementProposal,
        )
        self._eval_candidates = eval_candidate_store or EvalCandidateStore(
            ".local/flywheel/eval_candidates.jsonl"
        )
        self._regression = regression_gate or RegressionGate()

    #: ---- feedback (spec §5-§8) -------------------------------------------------
    async def capture_feedback(
        self,
        *,
        trace_id: str,
        query: str,
        answer: str = "",
        feedback_type: FeedbackType,
        comment: str | None = None,
        citations: list[str] | None = None,
    ) -> FeedbackEvent:
        """Record one human feedback event, always linked to ``trace_id``."""
        event = FeedbackEvent(
            feedback_id=make_id("fb"),
            trace_id=trace_id,
            query=query,
            answer=answer,
            feedback_type=feedback_type,
            comment=comment,
            citations=list(citations or []),
            created_at=utc_now_iso(),
        )
        await self._feedback.save(event)
        return event

    #: ---- candidates (spec §46-§47) ----------------------------------------------
    def create_candidates(
        self,
        result: AgentResult,
        events: list[TraceEvent] | None = None,
        feedback: FeedbackEvent | None = None,
    ) -> list[ReviewCandidate]:
        """Generate candidates from a runtime run and queue them for review."""
        candidates = self._generator.generate(result, events=events, feedback=feedback)
        for candidate in candidates:
            self._queue.add(candidate)
        return candidates

    #: ---- review (spec §17-§19) ---------------------------------------------------
    def review_candidate(
        self,
        candidate_id: str,
        *,
        decision: ReviewStatus,
        category: ImprovementCategory | None = None,
        failure_layer: object = None,
        notes: str = "",
        reviewed_by: str | None = None,
    ) -> ReviewCandidate | None:
        """Record a human's verdict on one candidate (mandatory gate §19)."""
        return self._queue.update(
            candidate_id,
            status=decision,
            category=category,
            failure_layer=failure_layer,
            notes=notes,
            reviewed_by=reviewed_by,
        )

    #: ---- proposals (spec §20-§21) -------------------------------------------------
    def create_proposal(
        self,
        candidate_ids: list[str],
        *,
        proposal_type: ProposalType | None = None,
        category: ImprovementCategory,
        title: str = "",
        description: str = "",
        proposed_action: str = "",
    ) -> ImprovementProposal | None:
        """Build + persist a proposal from reviewed candidate(s).

        The reviewer passes ``proposal_type`` explicitly (spec §59); when
        omitted we suggest one from ``category`` but the caller may still
        override.
        """
        candidates = [c for c in (self._queue.get(i) for i in candidate_ids) if c is not None]
        if not candidates:
            return None
        proposal = build_proposal(
            candidates,
            proposal_type=proposal_type or suggest_proposal_type(category),
            category=category,
            title=title,
            description=description,
            proposed_action=proposed_action,
        )
        self._proposals.append(proposal)
        for candidate in candidates:
            self._queue.update(candidate.candidate_id, status=ReviewStatus.PROPOSAL_CREATED)
        return proposal

    def get_proposal(self, proposal_id: str) -> ImprovementProposal | None:
        return cast(ImprovementProposal | None, self._proposals.get(proposal_id))

    def list_proposals(self) -> list[ImprovementProposal]:
        return self._proposals.read()

    def accept_proposal(self, proposal_id: str) -> ImprovementProposal | None:
        return self._set_proposal_status(proposal_id, ProposalStatus.ACCEPTED)

    def reject_proposal(self, proposal_id: str) -> ImprovementProposal | None:
        return self._set_proposal_status(proposal_id, ProposalStatus.REJECTED)

    def _set_proposal_status(
        self, proposal_id: str, status: ProposalStatus
    ) -> ImprovementProposal | None:
        records: list[ImprovementProposal] = self._proposals.read()
        for i, record in enumerate(records):
            if record.proposal_id != proposal_id:
                continue
            records[i] = record.model_copy(update={"status": status})
            self._proposals.replace(records)
            return records[i]
        return None

    #: ---- eval candidates (spec §22-§26) -------------------------------------------
    def create_eval_candidate(
        self,
        *,
        proposal_id: str,
        candidate_id: str,
        query: str,
        category: str = "",
        should_retrieve: bool = False,
        expected_intent: object | None = None,
        expected_strategy: object | None = None,
        expected_sources: list[str] | None = None,
        expected_answer_terms: list[str] | None = None,
        expect_abstain: bool = False,
        feedback: FeedbackEvent | None = None,
    ) -> EvalCandidate | None:
        """Create a labeled eval candidate from an ACCEPTED proposal + reviewed case.

        Refused when the proposal is not ACCEPTED (rejected proposals or
        unreviewed candidates cannot be promoted, spec §60).
        """
        proposal = self.get_proposal(proposal_id)
        candidate = self._queue.get(candidate_id)
        if proposal is None or proposal.status is not ProposalStatus.ACCEPTED:
            return None
        #: the candidate is human-endorsed when ACCEPTED, or once a proposal
        #: has been raised for it (create_proposal flips it to PROPOSAL_CREATED).
        if candidate is None or candidate.status not in (
            ReviewStatus.ACCEPTED,
            ReviewStatus.PROPOSAL_CREATED,
        ):
            return None
        if proposal.proposal_type is not ProposalType.ADD_EVAL_CASE:
            return None
        eval_candidate = build_eval_candidate(
            query=query,
            category=category,
            should_retrieve=should_retrieve,
            expected_intent=expected_intent,
            expected_strategy=expected_strategy,
            expected_sources=expected_sources,
            expected_answer_terms=expected_answer_terms,
            expect_abstain=expect_abstain,
            proposal=proposal,
            candidate=candidate,
            feedback=feedback,
        )
        self._eval_candidates.add(eval_candidate)
        return eval_candidate

    def list_eval_candidates(self) -> list[EvalCandidate]:
        return self._eval_candidates.list_all()

    def promote_eval_candidate(
        self,
        candidate_id: str,
        *,
        dataset_cases: list[EvalCase] | None = None,
    ) -> PromotionResult:
        """Explicitly promote an eval candidate into the given dataset cases."""
        return self._eval_candidates.try_promote(
            candidate_id, existing_cases=list(dataset_cases or [])
        )

    #: ---- regression (spec §31-§34) ---------------------------------------------------
    def run_regression(
        self,
        proposal_id: str,
        *,
        baseline: MetricSummary,
        candidate: MetricSummary,
        tests_passed: bool,
    ) -> RegressionCheckResult:
        """Run the regression gate for a proposal (records only)."""
        return self._regression.check(
            proposal_id, baseline=baseline, candidate=candidate, tests_passed=tests_passed
        )

    #: ---- reporting (spec §53-§55) -----------------------------------------------------
    def flywheel_metrics(self) -> FlywheelMetrics:
        """Aggregate current flywheel counters."""
        return compute_flywheel_metrics(
            feedback_events=self._feedback.list_all(),
            review_candidates=self._queue.list_all(),
            proposals=self._proposals.read(),
            eval_candidates=self._eval_candidates.list_all(),
        )

    def report(self, *, dataset_path: str = "", scope: str = "development/demo data") -> str:
        return format_flywheel_report(
            self.flywheel_metrics(), dataset_path=dataset_path, scope=scope
        )
