"""Data Flywheel domain model (Stage 5.2).

A human-reviewed, auditable, reproducible, regression-gated loop that
turns real runtime queries / feedback / failures into improvement
proposals and regression cases -- WITHOUT ever modifying the prompt, the
router policy, or the knowledge base (spec §2/§19/§28/§35).

Framework/provider-neutral: these types never import LightRAG, an adapter,
or a provider SDK (openai). They reuse the existing ``Trace`` /
``AgentResult`` / ``EvalCase`` contracts rather than duplicating the
runtime or evaluation models (spec §44/§45).

Data flow (spec §36):

    FeedbackEvent -> ReviewCandidate -> Human Review -> ImprovementProposal
    -> Candidate Artifact (EvalCandidate) -> Regression Result -> Human Decision

Only explicit, auditable data is stored: user query, tool query, routing
decisions, tool-results summary, citations, final answer. No
chain-of-thought / hidden reasoning is ever captured (spec §42).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from polaris_agentic_rag.retrieval.models import RetrievalIntent, RetrievalStrategy

__all__ = [
    "FeedbackType",
    "FeedbackEvent",
    "ReviewSource",
    "ReviewPriority",
    "ReviewStatus",
    "ReviewCandidate",
    "FailureLayer",
    "ImprovementCategory",
    "ProposalType",
    "ProposalStatus",
    "ImprovementProposal",
    "EvalPromotionStatus",
    "EvalCandidate",
    "RegressionCheckResult",
    "FlywheelMetrics",
]


class FeedbackType(str, Enum):
    """Why the user reacted the way they did (spec §5).

    Not a binary thumbs_up/down: production analysis needs to know *why*.
    ``POSITIVE`` is the only non-negative value.
    """

    POSITIVE = "POSITIVE"
    INCORRECT = "INCORRECT"
    INCOMPLETE = "INCOMPLETE"
    UNSUPPORTED = "UNSUPPORTED"
    IRRELEVANT = "IRRELEVANT"
    SHOULD_HAVE_RETRIEVED = "SHOULD_HAVE_RETRIEVED"
    SHOULD_NOT_HAVE_RETRIEVED = "SHOULD_NOT_HAVE_RETRIEVED"
    BAD_CITATION = "BAD_CITATION"
    OTHER = "OTHER"


#: FeedbackTypes that count as "negative" (a problem worth reviewing).
_NEGATIVE_FEEDBACK_TYPES = frozenset(
    {
        FeedbackType.INCORRECT,
        FeedbackType.INCOMPLETE,
        FeedbackType.UNSUPPORTED,
        FeedbackType.IRRELEVANT,
        FeedbackType.SHOULD_HAVE_RETRIEVED,
        FeedbackType.SHOULD_NOT_HAVE_RETRIEVED,
        FeedbackType.BAD_CITATION,
        FeedbackType.OTHER,
    }
)


def is_negative_feedback(feedback_type: FeedbackType) -> bool:
    """Return True when a feedback type flags a problem worth reviewing."""
    return feedback_type in _NEGATIVE_FEEDBACK_TYPES


class FeedbackEvent(BaseModel):
    """One piece of user/human feedback, always linked to a runtime trace.

    Deliberately small (spec §6/§7): it does NOT copy the full evidence,
    full trace, or model message history -- those are recovered through
    ``trace_id`` when analysis needs them.
    """

    feedback_id: str
    trace_id: str
    query: str
    answer: str = ""
    feedback_type: FeedbackType
    comment: str | None = None
    citations: list[str] = Field(default_factory=list)
    created_at: str = ""


class ReviewSource(str, Enum):
    """Where a review candidate came from (spec §11)."""

    USER_FEEDBACK = "USER_FEEDBACK"
    EVALUATION_FAILURE = "EVALUATION_FAILURE"
    RUNTIME_SIGNAL = "RUNTIME_SIGNAL"


class ReviewPriority(str, Enum):
    """Coarse, decision-useful priority (spec §49) -- no fake score formula."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReviewStatus(str, Enum):
    """Lifecycle of a review candidate (spec §17)."""

    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NO_ACTION = "NO_ACTION"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"


class FailureLayer(str, Enum):
    """Where a failure happened (spec §15) -- layered attribution.

    Continuation of the Stage 5.1 attribution principle: an Agent-rewritten
    tool-query that loses the retrieval signal is ``QUERY_REWRITE``, NOT
    ``ROUTER`` (the Router classified the original query correctly).
    """

    INVOCATION = "INVOCATION"
    QUERY_REWRITE = "QUERY_REWRITE"
    ROUTER = "ROUTER"
    RETRIEVAL = "RETRIEVAL"
    KNOWLEDGE_BASE = "KNOWLEDGE_BASE"
    CITATION = "CITATION"
    SYNTHESIS = "SYNTHESIS"
    EVALUATION = "EVALUATION"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    NONE = "NONE"


class ImprovementCategory(str, Enum):
    """Flywheel-level problem taxonomy (spec §14) -- not one big BAD_ANSWER.

    ``KNOWLEDGE_GAP`` is a first-class type: retrieval happened, no
    supporting evidence exists, and the Agent correctly abstained is a real
    problem class, not an Agent failure (spec §13).
    """

    RETRIEVAL_INVOCATION_FALSE_NEGATIVE = "RETRIEVAL_INVOCATION_FALSE_NEGATIVE"
    RETRIEVAL_INVOCATION_FALSE_POSITIVE = "RETRIEVAL_INVOCATION_FALSE_POSITIVE"
    ROUTER_POLICY_MISMATCH = "ROUTER_POLICY_MISMATCH"
    QUERY_REWRITE_INTENT_DRIFT = "QUERY_REWRITE_INTENT_DRIFT"
    SOURCE_MISS = "SOURCE_MISS"
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    CITATION_UNGROUNDED = "CITATION_UNGROUNDED"
    CITATION_INCOMPLETE = "CITATION_INCOMPLETE"
    ANSWER_INCORRECT = "ANSWER_INCORRECT"
    ANSWER_INCOMPLETE = "ANSWER_INCOMPLETE"
    ANSWER_UNSUPPORTED = "ANSWER_UNSUPPORTED"
    ABSTENTION_MISSED = "ABSTENTION_MISSED"
    UNNECESSARY_ABSTENTION = "UNNECESSARY_ABSTENTION"
    PROMPT_POLICY_GAP = "PROMPT_POLICY_GAP"
    EVALUATION_LABEL_ISSUE = "EVALUATION_LABEL_ISSUE"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"


class ProposalType(str, Enum):
    """What the proposal suggests changing -- applied only after human sign-off.

    Stage 5.2 only *generates* proposals; nothing is applied automatically
    (spec §21/§23/§28/§30).
    """

    ADD_EVAL_CASE = "ADD_EVAL_CASE"
    UPDATE_KNOWLEDGE_BASE = "UPDATE_KNOWLEDGE_BASE"
    ADJUST_RETRIEVAL_INVOCATION_POLICY = "ADJUST_RETRIEVAL_INVOCATION_POLICY"
    ADJUST_ROUTER_POLICY = "ADJUST_ROUTER_POLICY"
    ADJUST_ORCHESTRATOR_PROMPT = "ADJUST_ORCHESTRATOR_PROMPT"
    DOCUMENT_LIMITATION = "DOCUMENT_LIMITATION"
    FIX_EVALUATION_LABEL = "FIX_EVALUATION_LABEL"
    NO_ACTION = "NO_ACTION"


class ProposalStatus(str, Enum):
    """Lifecycle of an improvement proposal (spec §20)."""

    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReviewCandidate(BaseModel):
    """One item queued for human review (spec §10/§19).

    A REFLECTIVE signal, not a verdict: entering the queue does NOT mean
    the system has a bug (e.g. ``KNOWLEDGE_GAP`` may be a valid gap).
    Review fields (category / failure_layer / notes) are filled by a human
    during review.
    """

    candidate_id: str
    trace_id: str
    source: ReviewSource
    reason: str
    priority: ReviewPriority
    status: ReviewStatus = ReviewStatus.PENDING
    #: ---- resolved during human review ----
    category: ImprovementCategory | None = None
    failure_layer: FailureLayer | None = None
    notes: str = ""
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    #: ---- lightweight, useful context for the reviewer ----
    feedback_id: str | None = None
    query: str = ""
    answer: str = ""
    citations: list[str] = Field(default_factory=list)
    tool_queries: list[str] = Field(default_factory=list)
    failure_signals: list[str] = Field(default_factory=list)
    created_at: str = ""


class ImprovementProposal(BaseModel):
    """A concrete, evidence-backed improvement suggestion (spec §20).

    Every proposal is traceable back through ``source_candidate_ids`` to a
    review candidate, then to feedback / a runtime signal, then to a trace
    (spec §37 / audit trail). ``category`` is the flywheel problem label;
    ``proposal_type`` is the kind of artifact the reviewer wants to create.
    """

    proposal_id: str
    source_candidate_ids: list[str] = Field(default_factory=list)
    category: ImprovementCategory
    proposal_type: ProposalType
    title: str = ""
    description: str = ""
    evidence: dict[str, object] = Field(default_factory=dict)
    proposed_action: str = ""
    status: ProposalStatus = ProposalStatus.OPEN
    created_at: str = ""


class EvalPromotionStatus(str, Enum):
    """Lifecycle of an eval-case candidate (spec §23/§24)."""

    PENDING = "PENDING"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"


class EvalCandidate(BaseModel):
    """A candidate labeled eval case, WITH full provenance (spec §23/§25).

    Holds the dataset labels (``should_retrieve`` / ``expected_*`` /
    ``expect_abstain``) plus an explicit audit chain back to
    review candidate -> proposal -> feedback / trace. Promotion into the
    formal dataset requires an explicit human action (spec §24).
    """

    candidate_id: str
    query: str
    category: str = ""
    should_retrieve: bool = False
    expected_intent: RetrievalIntent | None = None
    expected_strategy: RetrievalStrategy | None = None
    expected_sources: list[str] = Field(default_factory=list)
    expected_answer_terms: list[str] = Field(default_factory=list)
    expect_abstain: bool = False
    #: ---- provenance (spec §23/§25/§61) ----
    proposal_id: str | None = None
    source_candidate_id: str | None = None
    feedback_id: str | None = None
    trace_id: str | None = None
    status: EvalPromotionStatus = EvalPromotionStatus.PENDING
    created_at: str = ""


class RegressionCheckResult(BaseModel):
    """Outcome of a regression gate for one proposal (spec §31).

    Records baseline / candidate metrics, their deltas, whether the hard
    deterministic gates passed, and the recommended decision. Decisions are
    recorded for a human; the flywheel never auto-applies a proposal.
    """

    proposal_id: str
    baseline_metrics: dict[str, float] = Field(default_factory=dict)
    candidate_metrics: dict[str, float] = Field(default_factory=dict)
    deltas: dict[str, float] = Field(default_factory=dict)
    hard_gate_ok: bool = True
    hard_gate_violations: list[str] = Field(default_factory=list)
    tests_passed: bool = False
    decision: str = "HUMAN_REVIEW"  #: ACCEPT / REJECT / HUMAN_REVIEW
    notes: str = ""


class FlywheelMetrics(BaseModel):
    """Simple, honest data-flywheel counters (spec §53/§54).

    No synthetic ``flywheel_score`` (spec §53): just events that are easy to
    explain. Rate fields are ``None`` when there is no real data -- never a
    fabricated baseline (spec §54).
    """

    feedback_count: int = 0
    positive_feedback_count: int = 0
    negative_feedback_count: int = 0
    review_candidate_count: int = 0
    pending_review_count: int = 0
    knowledge_gap_count: int = 0
    query_rewrite_drift_count: int = 0
    proposal_count: int = 0
    eval_candidate_count: int = 0
    accepted_proposal_count: int = 0
    rejected_proposal_count: int = 0
    #: production-oriented (spec §54) -- None unless real data exists
    feedback_to_eval_conversion_rate: float | None = None
    knowledge_gap_rate: float | None = None
