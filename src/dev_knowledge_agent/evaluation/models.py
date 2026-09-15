"""Evaluation domain model (Stage 5).

``EvalCase`` is the application-owned unit of the evaluation dataset
(spec §5): it carries NO LightRAG ``QueryParam`` and only labels that mean
something at the application level (tool selection, routing policy,
expected sources / key terms, abstention).

``EvalCaseResult`` / ``EvalRunResult`` / ``MetricSummary`` (spec §21) keep
every case's actuals plus the aggregated summary so the report can be
reproduced from a single JSON file.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from dev_knowledge_agent.observability.models import FailureCategory
from dev_knowledge_agent.retrieval.models import RetrievalIntent, RetrievalStrategy

__all__ = [
    "EvalCase",
    "EvalCaseResult",
    "EvalRunResult",
    "MetricSummary",
]


class EvalCase(BaseModel):
    """One labeled evaluation sample (spec §5/§6).

    ``expected_intent`` / ``expected_strategy`` are the *project baseline
    expectation* -- the deterministic Router's policy -- NOT ground truth
    about which strategy is objectively best (spec §10).
    """

    id: str
    query: str
    category: str
    should_call_tool: bool = False
    expected_intent: RetrievalIntent | None = None
    expected_strategy: RetrievalStrategy | None = None
    expected_sources: list[str] = Field(default_factory=list)
    expected_answer_terms: list[str] = Field(default_factory=list)
    expect_abstain: bool = False


class EvalCaseResult(BaseModel):
    """Full record of one evaluated case (expected + actual + per-dimension verdicts)."""

    case_id: str
    query: str
    category: str
    #: ---- expected ----
    should_call_tool: bool
    expected_intent: RetrievalIntent | None = None
    expected_strategy: RetrievalStrategy | None = None
    expected_sources: list[str] = Field(default_factory=list)
    expected_answer_terms: list[str] = Field(default_factory=list)
    expect_abstain: bool = False
    #: ---- actual run ----
    status: str = "SUCCESS"
    tool_called: bool = False
    actual_intent: RetrievalIntent | None = None
    actual_strategy: RetrievalStrategy | None = None
    fallback_used: bool = False
    no_evidence: bool = False
    actual_sources: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    answer: str = ""
    abstained: bool = False
    #: ---- per-dimension verdicts (None = not applicable) ----
    tool_selection_correct: bool | None = None
    intent_match: bool | None = None
    strategy_match: bool | None = None
    source_recall: float | None = None
    answer_matched_terms: list[str] = Field(default_factory=list)
    answer_missing_terms: list[str] = Field(default_factory=list)
    answer_terms_all_present: bool | None = None
    citation_grounded: bool | None = None
    citation_source_recall: float | None = None
    #: ---- observability ----
    trace_id: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    failure_category: FailureCategory | None = None
    failure_message: str | None = None


class MetricSummary(BaseModel):
    """Human-readable aggregate summary (spec §42). None = not computable."""

    sample_count: int = 0
    #: tool selection (Stage 4 core capability, spec §8)
    tool_selection_accuracy: float | None = None
    tool_call_precision: float | None = None
    tool_call_recall: float | None = None
    false_positive_count: int = 0
    false_negative_count: int = 0
    #: routing (spec §9) -- measures *policy consistency*, not objective truth
    intent_accuracy: float | None = None
    strategy_accuracy: float | None = None
    fallback_rate: float | None = None
    #: retrieval / source coverage (spec §11/§12)
    expected_source_recall: float | None = None
    no_evidence_rate: float | None = None
    #: citation (spec §14/§15)
    citation_grounded_rate: float | None = None
    citation_source_recall: float | None = None
    #: answer / abstention (spec §17/§18)
    answer_term_match_rate: float | None = None
    abstention_accuracy: float | None = None
    #: latency / tokens (spec §31/§30)
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_tokens: int | None = None
    #: failures (spec §32); NO_EVIDENCE is a business outcome, listed separately
    failure_counts: dict[str, int] = Field(default_factory=dict)
    failed_case_ids: list[str] = Field(default_factory=list)


class EvalRunResult(BaseModel):
    """One full evaluation run: dataset meta + cases + metrics."""

    dataset: str = ""
    run_at: str = ""
    sample_count: int = 0
    cases: list[EvalCaseResult] = Field(default_factory=list)
    metrics: MetricSummary = Field(default_factory=MetricSummary)
