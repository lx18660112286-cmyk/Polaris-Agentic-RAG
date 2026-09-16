"""Eval-case candidate store + explicit promotion (spec §22-§26, §60).

A reviewer-approved problem can become a labeled ``EvalCandidate`` -- but
promotion into the *formal* dataset is an explicit, deduplicating, human
action (spec §24). Nothing here auto-appends to the real dataset.

Deduplication (spec §26) is intentionally simple -- strip, casefold and
whitespace normalization -- NOT an embedding-based similarity.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from polaris_agentic_rag.evaluation.models import EvalCase
from polaris_agentic_rag.flywheel.ids import utc_now_iso
from polaris_agentic_rag.flywheel.models import (
    EvalCandidate,
    EvalPromotionStatus,
    FeedbackEvent,
    ImprovementProposal,
    ProposalType,
    ReviewCandidate,
)
from polaris_agentic_rag.flywheel.repository import JsonlStore

__all__ = [
    "EvalCandidateStore",
    "PromotionResult",
    "is_duplicate_query",
    "normalize_query",
    "proposal_for_candidate",
]

_WS_RUN = re.compile(r"\s+")


def normalize_query(query: str) -> str:
    """Strip, collapse whitespace and casefold a query (spec §26)."""
    return _WS_RUN.sub(" ", (query or "").strip()).casefold()


def is_duplicate_query(
    query: str, *collections: list[EvalCandidate] | list[EvalCase] | list[object]
) -> bool:
    """True when ``query`` (normalized) already exists in any collection.

    Each collection is a list of objects that expose a ``query`` attribute
    (EvalCandidate / EvalCase / ...).
    """
    normalized = normalize_query(query)
    for items in collections:
        for item in items:
            value = getattr(item, "query", None)
            if value is not None and normalize_query(str(value)) == normalized:
                return True
    return False


class PromotionResult(BaseModel):
    """Outcome of trying to promote one eval candidate (spec §24/§26)."""

    candidate_id: str
    promoted: bool
    reason: str
    eval_case: EvalCase | None = None


class EvalCandidateStore:
    """Persists EvalCandidates to ``.local/flywheel/eval_candidates.jsonl``."""

    def __init__(
        self,
        path: str | Path,
        *,
        dataset_cases: list[EvalCase] | None = None,
    ) -> None:
        self._store = JsonlStore(path, id_field="candidate_id", model=EvalCandidate)
        self._loaded_dataset = list(dataset_cases or [])

    @property
    def path(self) -> Path:
        return self._store.path

    def add(self, candidate: EvalCandidate) -> None:
        """Queue a labeled eval candidate (not yet promoted)."""
        self._store.append(candidate)

    def get(self, candidate_id: str) -> EvalCandidate | None:
        return cast(EvalCandidate | None, self._store.get(candidate_id))

    def list_all(self, status: EvalPromotionStatus | None = None) -> list[EvalCandidate]:
        records: list[EvalCandidate] = self._store.read()
        if status is None:
            return records
        return [c for c in records if c.status is status]

    def mark(self, candidate_id: str, status: EvalPromotionStatus) -> EvalCandidate | None:
        records: list[EvalCandidate] = self._store.read()
        for i, record in enumerate(records):
            if record.candidate_id != candidate_id:
                continue
            records[i] = record.model_copy(update={"status": status})
            self._store.replace(records)
            return records[i]
        return None

    def try_promote(
        self,
        candidate_id: str,
        *,
        existing_cases: list[EvalCase],
    ) -> PromotionResult:
        """Attempt to promote one candidate into ``existing_cases``.

        Promotion is refused when the candidate is not PENDING (already
        promoted / rejected) or the (normalized) query already exists in the
        candidate store or the target dataset.
        """
        candidate = self.get(candidate_id)
        if candidate is None:
            return PromotionResult(
                candidate_id=candidate_id, promoted=False, reason="candidate not found"
            )
        if candidate.status is not EvalPromotionStatus.PENDING:
            return PromotionResult(
                candidate_id=candidate_id,
                promoted=False,
                reason=f"candidate not pending (status={candidate.status.value})",
            )
        #: dedup against OTHER queued candidates + the target dataset (never
        #: against the candidate being promoted itself).
        others = [c for c in self.list_all() if c.candidate_id != candidate_id]
        if is_duplicate_query(candidate.query, others, existing_cases):
            self.mark(candidate_id, EvalPromotionStatus.REJECTED)
            return PromotionResult(
                candidate_id=candidate_id,
                promoted=False,
                reason="duplicate query (normalized) already present",
            )
        eval_case = _to_eval_case(candidate)
        self.mark(candidate_id, EvalPromotionStatus.PROMOTED)
        return PromotionResult(
            candidate_id=candidate_id,
            promoted=True,
            reason="promoted",
            eval_case=eval_case,
        )


def proposal_for_candidate(
    proposal: ImprovementProposal,
    candidate: ReviewCandidate,
) -> bool:
    """Whether a proposal is endorsed to turn this reviewed candidate into an eval case."""
    return (
        proposal.proposal_type is ProposalType.ADD_EVAL_CASE
        and candidate.candidate_id in proposal.source_candidate_ids
    )


def build_eval_candidate(
    *,
    query: str,
    category: str = "",
    should_retrieve: bool,
    expected_intent: object | None = None,
    expected_strategy: object | None = None,
    expected_sources: list[str] | None = None,
    expected_answer_terms: list[str] | None = None,
    expect_abstain: bool = False,
    proposal: ImprovementProposal,
    candidate: ReviewCandidate,
    feedback: FeedbackEvent | None = None,
) -> EvalCandidate:
    """Build a labeled EvalCandidate with full provenance (spec §23/§61).

    ``proposal`` must be an ``ADD_EVAL_CASE`` proposal anchored to
    ``candidate`` (spec §22); otherwise the artifact would lack a valid
    audit chain.
    """
    if not proposal_for_candidate(proposal, candidate):
        raise ValueError("proposal must be ADD_EVAL_CASE and reference the source candidate")
    from polaris_agentic_rag.flywheel.ids import make_id

    return EvalCandidate(
        candidate_id=make_id("evc"),
        query=query,
        category=category,
        should_retrieve=should_retrieve,
        expected_intent=expected_intent,  # type: ignore[arg-type]
        expected_strategy=expected_strategy,  # type: ignore[arg-type]
        expected_sources=list(expected_sources or []),
        expected_answer_terms=list(expected_answer_terms or []),
        expect_abstain=expect_abstain,
        proposal_id=proposal.proposal_id,
        source_candidate_id=candidate.candidate_id,
        feedback_id=feedback.feedback_id if feedback else candidate.feedback_id,
        trace_id=candidate.trace_id,
        created_at=utc_now_iso(),
    )


def _to_eval_case(candidate: EvalCandidate) -> EvalCase:
    """Map an EvalCandidate onto the REUSED formal EvalCase model (spec §45).

    ``EvalCase`` carries the project-baseline expectation fields; the audit
    chain lives on the candidate / proposal (origin provenance is kept on the
    candidate, not re-invented here).
    """
    return EvalCase(
        id=candidate.candidate_id,
        query=candidate.query,
        category=candidate.category,
        should_call_tool=candidate.should_retrieve,
        expected_intent=candidate.expected_intent,
        expected_strategy=candidate.expected_strategy,
        expected_sources=list(candidate.expected_sources),
        expected_answer_terms=list(candidate.expected_answer_terms),
        expect_abstain=candidate.expect_abstain,
    )
