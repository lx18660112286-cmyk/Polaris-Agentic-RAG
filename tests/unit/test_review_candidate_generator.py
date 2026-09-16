"""Offline tests for ReviewCandidateGenerator deterministic rules (spec §46/§47).

Verifies Rules A-E from a synthetic AgentResult + optional feedback:
A  negative feedback -> USER_FEEDBACK candidate
B  NO_EVIDENCE       -> KNOWLEDGE_GAP candidate
C  query-rewrite drift -> routing review candidate
D  ungrounded citation -> HIGH priority candidate
E  system failure       -> infrastructure candidate
"""

from __future__ import annotations

from polaris_agentic_rag.agent.models import AgentResult, AgentStatus, ToolCallRecord
from polaris_agentic_rag.evaluation.metrics import classify_failure
from polaris_agentic_rag.flywheel.candidate_generator import ReviewCandidateGenerator
from polaris_agentic_rag.flywheel.models import (
    FeedbackEvent,
    FeedbackType,
    ImprovementCategory,
    ReviewPriority,
    ReviewSource,
    ReviewStatus,
)
from polaris_agentic_rag.observability.models import FailureCategory
from polaris_agentic_rag.retrieval.models import (
    RetrievalIntent,
    RetrievalStrategy,
    RoutingStep,
)
from polaris_agentic_rag.retrieval.router import QueryRouter


def _ok_result(**kwargs) -> AgentResult:
    base: dict = {
        "status": AgentStatus.SUCCESS,
        "trace_id": "t1",
        "original_query": "how long is an access token valid?",
    }
    base.update(kwargs)
    return AgentResult(**base)


def test_no_signals_yields_no_candidates() -> None:
    gen = ReviewCandidateGenerator()
    assert gen.generate(_ok_result()) == []


def test_rule_a_negative_feedback_creates_user_feedback_candidate() -> None:
    gen = ReviewCandidateGenerator()
    feedback = FeedbackEvent(
        feedback_id="fb1",
        trace_id="t1",
        query="q",
        answer="a",
        feedback_type=FeedbackType.INCORRECT,
    )
    candidates = gen.generate(_ok_result(), feedback=feedback)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.source is ReviewSource.USER_FEEDBACK
    assert c.feedback_id == "fb1"
    assert c.priority is ReviewPriority.MEDIUM


def test_rule_a_bad_citation_feedback_is_high_priority() -> None:
    gen = ReviewCandidateGenerator()
    feedback = FeedbackEvent(
        feedback_id="fb1",
        trace_id="t1",
        query="q",
        feedback_type=FeedbackType.BAD_CITATION,
    )
    candidates = gen.generate(_ok_result(), feedback=feedback)
    assert candidates[0].priority is ReviewPriority.HIGH


def test_positive_feedback_generates_no_candidate() -> None:
    gen = ReviewCandidateGenerator()
    feedback = FeedbackEvent(
        feedback_id="fb1",
        trace_id="t1",
        query="q",
        feedback_type=FeedbackType.POSITIVE,
    )
    assert gen.generate(_ok_result(), feedback=feedback) == []


def test_rule_b_no_evidence_creates_knowledge_gap_candidate() -> None:
    gen = ReviewCandidateGenerator()
    result = _ok_result(
        tool_calls=[
            ToolCallRecord(
                name="search_dev_knowledge",
                arguments={"query": "q"},
                result_status="NO_EVIDENCE",
            )
        ]
    )
    candidates = gen.generate(result)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.category is ImprovementCategory.KNOWLEDGE_GAP
    assert c.source is ReviewSource.RUNTIME_SIGNAL
    assert "NO_EVIDENCE" in c.failure_signals


def test_rule_e_system_failure_creates_infrastructure_candidate() -> None:
    gen = ReviewCandidateGenerator()
    result = _ok_result(status=AgentStatus.TOOL_ERROR)
    assert classify_failure(result) is FailureCategory.TOOL_ERROR
    candidates = gen.generate(result)
    assert candidates, "expected an infrastructure candidate"
    c = candidates[0]
    assert c.priority is ReviewPriority.HIGH
    assert c.source is ReviewSource.RUNTIME_SIGNAL


def test_rule_d_ungrounded_citation_high_priority() -> None:
    gen = ReviewCandidateGenerator()
    result = _ok_result(
        answer="see doc.md",
        citations=["doc.md", "missing.md"],
        tool_calls=[
            ToolCallRecord(
                name="search_dev_knowledge",
                arguments={"query": "q"},
                result_status="SUCCESS",
                sources=["doc.md"],
            )
        ],
    )
    candidates = gen.generate(result)
    assert any(c.category is ImprovementCategory.CITATION_UNGROUNDED for c in candidates)
    ungrounded = [c for c in candidates if c.category is ImprovementCategory.CITATION_UNGROUNDED][0]
    assert ungrounded.priority is ReviewPriority.HIGH
    assert any("missing.md" in s for s in ungrounded.failure_signals)


def test_rule_d_grounded_citation_no_candidate() -> None:
    gen = ReviewCandidateGenerator()
    result = _ok_result(
        citations=["doc.md"],
        tool_calls=[
            ToolCallRecord(
                name="search_dev_knowledge",
                arguments={"query": "q"},
                result_status="SUCCESS",
                sources=["doc.md"],
            )
        ],
    )
    assert all(
        c.category is not ImprovementCategory.CITATION_UNGROUNDED for c in gen.generate(result)
    )


def test_rule_c_rewrite_drift_creates_drift_candidate() -> None:
    router = QueryRouter()
    gen = ReviewCandidateGenerator(router=router)
    original = "how long is an access token valid?"
    orig_intent = router.route(original).intent
    #: pick a *different* final answer as the drifted intent
    drifted = next(
        i for i in RetrievalIntent if i is not orig_intent
    )  # any other intent proves the rewrite drifted
    result = _ok_result(
        original_query=original,
        routing_steps=[
            RoutingStep(
                step_index=0,
                tool_call_id="call1",
                original_user_query=original,
                tool_query="what",
                intent=drifted,
                strategy=RetrievalStrategy.FOCUSED,
            )
        ],
    )
    candidates = gen.generate(result)
    assert any(c.category is ImprovementCategory.QUERY_REWRITE_INTENT_DRIFT for c in candidates)


def test_rule_c_no_drift_no_candidate() -> None:
    router = QueryRouter()
    gen = ReviewCandidateGenerator(router=router)
    original = "how long is an access token valid?"
    orig_intent = router.route(original).intent
    result = _ok_result(
        original_query=original,
        routing_steps=[
            RoutingStep(
                step_index=0,
                tool_call_id="call1",
                original_user_query=original,
                tool_query="access token validity",
                intent=orig_intent,
                strategy=RetrievalStrategy.FOCUSED,
            )
        ],
    )
    assert all(
        c.category is not ImprovementCategory.QUERY_REWRITE_INTENT_DRIFT
        for c in gen.generate(result)
    )


def test_combined_rules_generate_multiple_candidates() -> None:
    gen = ReviewCandidateGenerator()
    feedback = FeedbackEvent(
        feedback_id="fb1",
        trace_id="t1",
        query="q",
        feedback_type=FeedbackType.INCOMPLETE,
    )
    result = _ok_result(
        answer="x",
        citations=["a.md"],
        tool_calls=[
            ToolCallRecord(
                name="search_dev_knowledge",
                arguments={"query": "q"},
                result_status="NO_EVIDENCE",
                sources=["a.md"],
            ),
            ToolCallRecord(
                name="search_dev_knowledge",
                arguments={"query": "q2"},
                result_status="NO_EVIDENCE",
            ),
        ],
    )
    candidates = gen.generate(result, feedback=feedback)
    assert len(candidates) >= 2  # Rule A + at least one Rule B
    assert all(c.status is ReviewStatus.PENDING for c in candidates)
