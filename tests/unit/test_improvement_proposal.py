"""Offline tests for ImprovementProposal construction (spec §20/§21/§29/§30).

A proposal is a suggestion only -- the flywheel never applies it. Tests
verify ``suggest_proposal_type`` defaults and that ``build_proposal``
auto-captures provenance for an audit trail.
"""

from __future__ import annotations

import pytest

from polaris_agentic_rag.flywheel.ids import make_id
from polaris_agentic_rag.flywheel.models import (
    ImprovementCategory,
    ProposalStatus,
    ProposalType,
    ReviewCandidate,
    ReviewPriority,
    ReviewSource,
)
from polaris_agentic_rag.flywheel.proposals import build_proposal, suggest_proposal_type


def _candidate(cid: str, trace_id: str, feedback_id: str | None = None) -> ReviewCandidate:
    return ReviewCandidate(
        candidate_id=cid,
        trace_id=trace_id,
        source=ReviewSource.USER_FEEDBACK,
        reason="r",
        priority=ReviewPriority.MEDIUM,
        feedback_id=feedback_id,
        query="what is the access token validity",
    )


def test_suggest_proposal_type_defaults() -> None:
    assert (
        suggest_proposal_type(ImprovementCategory.KNOWLEDGE_GAP)
        is ProposalType.UPDATE_KNOWLEDGE_BASE
    )
    assert (
        suggest_proposal_type(ImprovementCategory.QUERY_REWRITE_INTENT_DRIFT)
        is ProposalType.ADJUST_ORCHESTRATOR_PROMPT
    )
    assert (
        suggest_proposal_type(ImprovementCategory.ROUTER_POLICY_MISMATCH)
        is ProposalType.ADJUST_ROUTER_POLICY
    )
    assert (
        suggest_proposal_type(ImprovementCategory.RETRIEVAL_INVOCATION_FALSE_NEGATIVE)
        is ProposalType.ADJUST_RETRIEVAL_INVOCATION_POLICY
    )
    assert (
        suggest_proposal_type(ImprovementCategory.EVALUATION_LABEL_ISSUE)
        is ProposalType.FIX_EVALUATION_LABEL
    )
    #: unknown category -> conservative DOCUMENT_LIMITATION
    assert (
        suggest_proposal_type(ImprovementCategory.ANSWER_INCORRECT)
        is ProposalType.DOCUMENT_LIMITATION
    )


def test_build_proposal_captures_provenance() -> None:
    cand_a = _candidate("c1", "t1", "fb1")
    cand_b = _candidate("c2", "t2")
    prop = build_proposal(
        [cand_a, cand_b],
        proposal_type=ProposalType.ADD_EVAL_CASE,
        category=ImprovementCategory.KNOWLEDGE_GAP,
        title="add case",
        proposed_action="add to dataset",
    )
    assert prop.proposal_type is ProposalType.ADD_EVAL_CASE
    assert prop.source_candidate_ids == ["c1", "c2"]
    assert prop.status is ProposalStatus.OPEN
    #: audit trail is captured automatically
    assert prop.evidence["feedback_ids"] == ["fb1"]
    assert set(prop.evidence["trace_ids"]) == {"t1", "t2"}
    assert "what is the access token validity" in prop.evidence["queries"]


def test_build_proposal_rejects_empty_candidates() -> None:
    with pytest.raises(ValueError):
        build_proposal(
            [],
            proposal_type=ProposalType.NO_ACTION,
            category=ImprovementCategory.NO_ACTION_REQUIRED,
        )


def test_proposal_is_evidence_backed_suggestion() -> None:
    cand = _candidate(make_id("cand"), "t1", "fb1")
    prop = build_proposal(
        [cand],
        proposal_type=ProposalType.UPDATE_KNOWLEDGE_BASE,
        category=ImprovementCategory.KNOWLEDGE_GAP,
    )
    #: the flywheel only WRITES the proposal record; it never mutates the KB.
    assert prop.proposed_action == ""
    assert prop.status is ProposalStatus.OPEN
