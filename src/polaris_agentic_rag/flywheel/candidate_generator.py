"""ReviewCandidateGenerator -- deterministic runtime -> review candidate rules.

Transforms a completed runtime (``AgentResult`` + ``TraceEvent`` stream +
optional ``FeedbackEvent``) into explicit ``ReviewCandidate`` objects so a
human can review failures WITHOUT guessing what happened (spec §46).

Pure logic is deterministic and offline-testable (spec §46): it only reads
the AgentResult / trace / feedback it was given and never touches the
prompt, router, or KB. Auto-queuing does NOT mean auto-verdict -- e.g.
``NO_EVIDENCE`` only produces a ``KNOWLEDGE_GAP`` *candidate* (spec §12/§13).

Minimal rules (spec §47):

    A  manual negative feedback                        -> USER_FEEDBACK
    B  NO_EVIDENCE                                    -> KNOWLEDGE_GAP (RUNTIME_SIGNAL)
    C  query-rewrite intent drift                      -> routing review
    D  citation validation failure (ungrounded)        -> HIGH-priority candidate
    E  model/tool/system error                         -> infrastructure candidate
"""

from __future__ import annotations

from polaris_agentic_rag.agent.models import AgentResult
from polaris_agentic_rag.evaluation.metrics import classify_failure
from polaris_agentic_rag.flywheel.ids import make_id, utc_now_iso
from polaris_agentic_rag.flywheel.models import (
    FeedbackEvent,
    FeedbackType,
    ImprovementCategory,
    ReviewCandidate,
    ReviewPriority,
    ReviewSource,
    is_negative_feedback,
)
from polaris_agentic_rag.observability.models import FailureCategory, TraceEvent
from polaris_agentic_rag.retrieval.router import QueryRouter

__all__ = ["ReviewCandidateGenerator"]

#: FailureCategories that indicate an infrastructure / system-level problem
#: (Rule E) as opposed to a business or diagnostic outcome.
_INFRA_FAILURES = frozenset(
    {
        FailureCategory.MODEL_ERROR,
        FailureCategory.TOOL_ERROR,
        FailureCategory.UNKNOWN_TOOL,
        FailureCategory.INVALID_TOOL_ARGUMENTS,
        FailureCategory.MAX_STEPS,
        FailureCategory.MAX_TOOL_CALLS,
        FailureCategory.RETRIEVAL_ERROR,
        FailureCategory.CITATION_ERROR,
    }
)


def _gather_tool_queries(result: AgentResult) -> list[str]:
    """Collect the tool queries actually sent to retrieval (routing-step order)."""
    queries = [step.tool_query for step in result.routing_steps if step.tool_query]
    for record in result.tool_calls:
        q = str(record.arguments.get("query") or "") if isinstance(record.arguments, dict) else ""
        if q and q not in queries:
            queries.append(q)
    return queries


def _gather_sources(result: AgentResult) -> set[str]:
    sources: set[str] = set()
    for record in result.tool_calls:
        sources.update(record.sources)
    return sources


class ReviewCandidateGenerator:
    """Produce ReviewCandidates from a runtime result (+ optional feedback)."""

    def __init__(self, router: QueryRouter | None = None) -> None:
        self._router = router

    def generate(
        self,
        result: AgentResult,
        events: list[TraceEvent] | None = None,
        feedback: FeedbackEvent | None = None,
    ) -> list[ReviewCandidate]:
        """Return candidates for one runtime result (spec §46/§47).

        ``events`` is accepted for API symmetry (spec §46 lists a Trace as
        input); the deterministic rules currently read ``AgentResult``, which
        already carries the correlated ids and routing steps.
        """
        del events  #: kept for the documented signature; rules read AgentResult
        candidates: list[ReviewCandidate] = []
        trace_id = result.trace_id
        tool_queries = _gather_tool_queries(result)
        sources = _gather_sources(result)

        #: Rule A -- manual negative feedback (spec §47A)
        if feedback is not None and is_negative_feedback(feedback.feedback_type):
            priority = (
                ReviewPriority.HIGH
                if feedback.feedback_type is FeedbackType.BAD_CITATION
                else ReviewPriority.MEDIUM
            )
            candidates.append(
                self._candidate(
                    trace_id=trace_id,
                    source=ReviewSource.USER_FEEDBACK,
                    reason=f"user feedback type={feedback.feedback_type.value}",
                    priority=priority,
                    result=result,
                    feedback_id=feedback.feedback_id,
                    tool_queries=tool_queries,
                    failure_signals=[f"USER_FEEDBACK:{feedback.feedback_type.value}"],
                )
            )

        #: Rule E -- infrastructure / system failure (spec §47E)
        failure_category = classify_failure(result)
        if failure_category is not None and failure_category in _INFRA_FAILURES:
            candidates.append(
                self._candidate(
                    trace_id=trace_id,
                    source=ReviewSource.RUNTIME_SIGNAL,
                    reason=f"system failure category={failure_category.value}",
                    priority=ReviewPriority.HIGH,
                    category=ImprovementCategory.ANSWER_UNSUPPORTED,
                    result=result,
                    feedback_id=feedback.feedback_id if feedback else None,
                    tool_queries=tool_queries,
                    failure_signals=[failure_category.value],
                )
            )

        #: Rule B -- NO_EVIDENCE -> knowledge gap candidate (spec §47B/§13)
        if any(r.result_status == "NO_EVIDENCE" for r in result.tool_calls):
            candidates.append(
                self._candidate(
                    trace_id=trace_id,
                    source=ReviewSource.RUNTIME_SIGNAL,
                    reason="retrieval happened but no supporting evidence exists",
                    priority=ReviewPriority.MEDIUM,
                    category=ImprovementCategory.KNOWLEDGE_GAP,
                    result=result,
                    feedback_id=feedback.feedback_id if feedback else None,
                    tool_queries=tool_queries,
                    failure_signals=["NO_EVIDENCE"],
                )
            )

        #: Rule D -- citation must be grounded in tool evidence (spec §47D/§52)
        ungrounded = sorted(set(result.citations) - sources)
        if ungrounded:
            candidates.append(
                self._candidate(
                    trace_id=trace_id,
                    source=ReviewSource.RUNTIME_SIGNAL,
                    reason=f"final answer cites sources absent from tool evidence: {ungrounded}",
                    priority=ReviewPriority.HIGH,
                    category=ImprovementCategory.CITATION_UNGROUNDED,
                    result=result,
                    feedback_id=feedback.feedback_id if feedback else None,
                    tool_queries=tool_queries,
                    failure_signals=[f"CITATION_UNGROUNDED:{name}" for name in ungrounded],
                )
            )

        #: Rule C -- query-rewrite intent drift (spec §47C/§15)
        drift = self._detect_rewrite_drift(result)
        if drift is not None:
            candidates.append(
                self._candidate(
                    trace_id=trace_id,
                    source=ReviewSource.RUNTIME_SIGNAL,
                    reason=f"agent-rewritten tool query changed retrieval intent: {drift}",
                    priority=ReviewPriority.MEDIUM,
                    category=ImprovementCategory.QUERY_REWRITE_INTENT_DRIFT,
                    result=result,
                    feedback_id=feedback.feedback_id if feedback else None,
                    tool_queries=tool_queries,
                    failure_signals=["QUERY_REWRITE_INTENT_DRIFT"],
                )
            )

        return candidates

    def _detect_rewrite_drift(self, result: AgentResult) -> str | None:
        """Return a description when the primary tool query drifted, else None.

        The router classifies the *original* user query; the primary routing
        step records the intent the *rewritten* tool query was routed to. A
        mismatch means the rewrite -- not the Router -- lost the signal
        (spec §15: attribute to QUERY_REWRITE, not ROUTER).
        """
        if self._router is None or not result.routing_steps or not result.original_query:
            return None
        original = result.routing_steps[0].original_user_query
        plan = self._router.route(original)
        orig_intent = plan.intent
        tool_intent = result.routing_steps[0].intent
        if orig_intent is tool_intent:
            return None
        return f"{orig_intent.value} -> {tool_intent.value}"

    @staticmethod
    def _candidate(
        *,
        trace_id: str | None,
        source: ReviewSource,
        reason: str,
        priority: ReviewPriority,
        result: AgentResult,
        tool_queries: list[str],
        failure_signals: list[str],
        category: ImprovementCategory | None = None,
        feedback_id: str | None = None,
    ) -> ReviewCandidate:
        return ReviewCandidate(
            candidate_id=make_id("cand"),
            trace_id=trace_id or "",
            source=source,
            reason=reason,
            priority=priority,
            category=category,
            feedback_id=feedback_id,
            query=result.original_query,
            answer=result.answer,
            citations=list(result.citations),
            tool_queries=tool_queries,
            failure_signals=failure_signals,
            created_at=utc_now_iso(),
        )
