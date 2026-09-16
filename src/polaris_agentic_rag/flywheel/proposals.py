"""ImprovementProposal construction (spec §20/§21/§29/§30).

A proposal is an evidence-backed *suggestion*, produced only after a human
reviews one or more candidates. The flywheel never applies a proposal
automatically (spec §21/§23/§28/§30). The reviewer decides the
``ProposalType`` (spec §59); :func:`suggest_proposal_type` offers a sensible
default from the review category but the reviewer can override it.
"""

from __future__ import annotations

from polaris_agentic_rag.flywheel.ids import make_id, utc_now_iso
from polaris_agentic_rag.flywheel.models import (
    ImprovementCategory,
    ImprovementProposal,
    ProposalType,
    ReviewCandidate,
)

__all__ = ["build_proposal", "suggest_proposal_type"]

#: Sensible default ProposalType for a reviewed improvement category (spec §21).
_CATEGORY_TO_PROPOSAL: dict[ImprovementCategory, ProposalType] = {
    ImprovementCategory.KNOWLEDGE_GAP: ProposalType.UPDATE_KNOWLEDGE_BASE,
    ImprovementCategory.QUERY_REWRITE_INTENT_DRIFT: ProposalType.ADJUST_ORCHESTRATOR_PROMPT,
    ImprovementCategory.ROUTER_POLICY_MISMATCH: ProposalType.ADJUST_ROUTER_POLICY,
    ImprovementCategory.RETRIEVAL_INVOCATION_FALSE_NEGATIVE: (
        ProposalType.ADJUST_RETRIEVAL_INVOCATION_POLICY
    ),
    ImprovementCategory.RETRIEVAL_INVOCATION_FALSE_POSITIVE: (
        ProposalType.ADJUST_RETRIEVAL_INVOCATION_POLICY
    ),
    ImprovementCategory.EVALUATION_LABEL_ISSUE: ProposalType.FIX_EVALUATION_LABEL,
    ImprovementCategory.NO_ACTION_REQUIRED: ProposalType.NO_ACTION,
}

_DEFAULT_PROPOSAL = ProposalType.DOCUMENT_LIMITATION


def suggest_proposal_type(category: ImprovementCategory) -> ProposalType:
    """Return the default ProposalType for a review category.

    The reviewer may override this (spec §59); it is only a starting point.
    """
    return _CATEGORY_TO_PROPOSAL.get(category, _DEFAULT_PROPOSAL)


def _candidate_evidence(candidates: list[ReviewCandidate]) -> dict[str, object]:
    """Bundle provenance so a proposal is auditable (spec §37/§61)."""
    return {
        "source_candidate_ids": [c.candidate_id for c in candidates],
        "trace_ids": sorted({c.trace_id for c in candidates if c.trace_id}),
        "feedback_ids": sorted({c.feedback_id for c in candidates if c.feedback_id}),
        "categories": sorted({c.category.value for c in candidates if c.category}),
        "failure_layers": sorted({c.failure_layer.value for c in candidates if c.failure_layer}),
        "queries": [c.query for c in candidates if c.query],
    }


def build_proposal(
    candidates: list[ReviewCandidate],
    *,
    proposal_type: ProposalType,
    category: ImprovementCategory,
    title: str = "",
    description: str = "",
    proposed_action: str = "",
) -> ImprovementProposal:
    """Build a proposal anchored to the reviewed candidate(s).

    ``proposal_type`` is the reviewer's decision (spec §59); ``category`` is
    the flywheel problem label. Provenance (candidate/trace/feedback ids)
    is captured automatically for the audit trail.
    """
    if not candidates:
        raise ValueError("build_proposal requires at least one source candidate")
    return ImprovementProposal(
        proposal_id=make_id("prop"),
        source_candidate_ids=[c.candidate_id for c in candidates],
        category=category,
        proposal_type=proposal_type,
        title=title,
        description=description,
        evidence=_candidate_evidence(candidates),
        proposed_action=proposed_action,
        created_at=utc_now_iso(),
    )
