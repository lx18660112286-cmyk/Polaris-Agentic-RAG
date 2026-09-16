"""Offline tests for EvalCandidate store + explicit promotion (spec §22-§26).

Covers ``normalize_query``/``is_duplicate_query`` deduplication and the
guard that only an ACCEPTED ``ADD_EVAL_CASE`` proposal anchored to the
reviewed candidate may become a labeled eval candidate (spec §60).
"""

from __future__ import annotations

import pytest

from polaris_agentic_rag.evaluation.models import EvalCase
from polaris_agentic_rag.flywheel.eval_promotion import (
    EvalCandidateStore,
    build_eval_candidate,
    is_duplicate_query,
    normalize_query,
    proposal_for_candidate,
)
from polaris_agentic_rag.flywheel.models import (
    EvalCandidate,
    EvalPromotionStatus,
    FeedbackEvent,
    FeedbackType,
    ImprovementCategory,
    ImprovementProposal,
    ProposalType,
    ReviewCandidate,
    ReviewPriority,
    ReviewSource,
    ReviewStatus,
)
from polaris_agentic_rag.retrieval.models import RetrievalIntent, RetrievalStrategy


def _candidate(cid: str = "c1") -> ReviewCandidate:
    return ReviewCandidate(
        candidate_id=cid,
        trace_id="t1",
        source=ReviewSource.USER_FEEDBACK,
        reason="r",
        priority=ReviewPriority.MEDIUM,
        status=ReviewStatus.ACCEPTED,
        query="what is the access token validity",
    )


def _proposal(candidate: ReviewCandidate, pid: str = "p1") -> ImprovementProposal:
    return ImprovementProposal(
        proposal_id=pid,
        source_candidate_ids=[candidate.candidate_id],
        category=ImprovementCategory.KNOWLEDGE_GAP,
        proposal_type=ProposalType.ADD_EVAL_CASE,
    )


def test_normalize_query_handles_whitespace_and_case() -> None:
    assert normalize_query("  What is   The    Validity  ") == "what is the validity"


def test_is_duplicate_query_matches_normalized() -> None:
    assert is_duplicate_query(
        "What is  the Validity", [EvalCandidate(candidate_id="e1", query="what is the validity")]
    )  # noqa: E501
    assert not is_duplicate_query("unique query", [EvalCandidate(candidate_id="e1", query="other")])


def test_is_duplicate_query_checks_dataset_cases() -> None:
    case = EvalCase(id="x", query="what is the access token validity", category="c")
    assert is_duplicate_query("  WHAT IS  THE  access token validity ", [], [case])
    assert not is_duplicate_query("different", [], [case])


def test_proposal_for_candidate_anchor() -> None:
    cand = _candidate()
    good = _proposal(cand)
    bad = _proposal(cand, "p2")
    bad.proposal_type = ProposalType.UPDATE_KNOWLEDGE_BASE
    assert proposal_for_candidate(good, cand)
    assert not proposal_for_candidate(bad, cand)


def test_build_eval_candidate_validates_proposal_binding() -> None:
    cand = _candidate()
    prop = _proposal(cand)
    evc = build_eval_candidate(
        query=cand.query,
        category="terminology",
        should_retrieve=True,
        expected_intent=RetrievalIntent.TERMINOLOGY,
        expected_strategy=RetrievalStrategy.FOCUSED,
        proposal=prop,
        candidate=cand,
    )
    assert evc.should_retrieve is True
    assert evc.expected_intent is RetrievalIntent.TERMINOLOGY
    assert evc.proposal_id == "p1"
    assert evc.source_candidate_id == "c1"
    assert evc.trace_id == "t1"
    assert evc.status is EvalPromotionStatus.PENDING


def test_build_eval_candidate_records_feedback_provenance() -> None:
    cand = _candidate()
    prop = _proposal(cand)
    feedback = FeedbackEvent(
        feedback_id="fb1", trace_id="t1", query="q", feedback_type=FeedbackType.INCOMPLETE
    )
    evc = build_eval_candidate(
        query=cand.query,
        category="c",
        should_retrieve=False,
        proposal=prop,
        candidate=cand,
        feedback=feedback,
    )
    assert evc.feedback_id == "fb1"


def test_build_eval_candidate_rejects_unbound_proposal() -> None:
    cand = _candidate("c1")
    other = _candidate("c2")
    prop = _proposal(other)  # references c2, not c1
    with pytest.raises(ValueError):
        build_eval_candidate(
            query="q",
            category="c",
            should_retrieve=False,
            proposal=prop,
            candidate=cand,
        )


def test_promote_flow_success(tmp_path) -> None:
    store = EvalCandidateStore(tmp_path / "eval_candidates.jsonl")
    cand = EvalCandidate(candidate_id="e1", query="what is the access token validity")
    store.add(cand)
    result = store.try_promote("e1", existing_cases=[])
    assert result.promoted is True
    assert result.eval_case is not None
    assert result.eval_case.query == cand.query
    assert store.get("e1").status is EvalPromotionStatus.PROMOTED


def test_promote_unknown_candidate(tmp_path) -> None:
    store = EvalCandidateStore(tmp_path / "eval_candidates.jsonl")
    result = store.try_promote("missing", existing_cases=[])
    assert result.promoted is False
    assert "not found" in result.reason


def test_promote_already_promoted_refused(tmp_path) -> None:
    store = EvalCandidateStore(tmp_path / "eval_candidates.jsonl")
    store.add(EvalCandidate(candidate_id="e1", query="q"))
    store.try_promote("e1", existing_cases=[])
    again = store.try_promote("e1", existing_cases=[])
    assert again.promoted is False


def test_promote_duplicate_query_marks_rejected(tmp_path) -> None:
    store = EvalCandidateStore(tmp_path / "eval_candidates.jsonl")
    store.add(EvalCandidate(candidate_id="e1", query="what is the validity"))
    store.add(EvalCandidate(candidate_id="e2", query="WHAT  IS the  validity"))
    result = store.try_promote("e2", existing_cases=[])
    assert result.promoted is False
    assert "duplicate" in result.reason
    assert store.get("e2").status is EvalPromotionStatus.REJECTED


def test_promote_duplicate_against_dataset(tmp_path) -> None:
    store = EvalCandidateStore(tmp_path / "eval_candidates.jsonl")
    existing = [EvalCase(id="x", query="what is the access token validity", category="c")]
    store.add(EvalCandidate(candidate_id="e1", query="WHAT  IS the  access token  validity"))
    result = store.try_promote("e1", existing_cases=existing)
    assert result.promoted is False


def test_persistence_survives_reload(tmp_path) -> None:
    store = EvalCandidateStore(tmp_path / "eval_candidates.jsonl")
    store.add(EvalCandidate(candidate_id="e1", query="q"))
    reloaded = EvalCandidateStore(tmp_path / "eval_candidates.jsonl")
    assert [c.candidate_id for c in reloaded.list_all()] == ["e1"]
