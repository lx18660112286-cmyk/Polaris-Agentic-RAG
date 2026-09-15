"""Evaluation domain model (Stage 5 / Stage 5.1).

``EvalCase`` is the application-owned unit of the evaluation dataset
(spec §5): it carries NO LightRAG ``QueryParam`` and only labels that mean
something at the application level (tool selection, routing policy,
expected sources / key terms, abstention, critical terms, spec §13).

``EvalCaseResult`` / ``EvalRunResult`` / ``MetricSummary`` (spec §21) keep
every case's actuals plus the aggregated summary so the report can be
reproduced from a single JSON file.

Stage 5.1 splits the former single "routing accuracy" into three layers
(spec §2/§21):

* Layer A -- tool selection (does the Agent consult the Tool at all?)
* Layer B -- Router Component (does QueryRouter classify the *original*
  dataset query according to policy?) -- evaluated bypassing the Agent.
* Layer C -- Agentic Retrieval (after the Agent's tool-query generation,
  did the retrieval intent remain correct?) -- uses the *primary* step,
  i.e. the first routing step of the request; later steps never overwrite
  it (spec §6-§8).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from polaris_agentic_rag.observability.models import FailureCategory
from polaris_agentic_rag.retrieval.models import (
    RetrievalIntent,
    RetrievalStrategy,
    RoutingStep,
)

__all__ = [
    "EvalCase",
    "EvalCaseResult",
    "EvalRunResult",
    "MetricSummary",
    "RouterComponentResult",
    "RouterComponentRunResult",
    "RouterComponentSummary",
]


class EvalCase(BaseModel):
    """One labeled evaluation sample (spec §5/§6).

    ``expected_intent`` / ``expected_strategy`` are the *project baseline
    expectation* -- the deterministic Router's policy -- NOT ground truth
    about which strategy is objectively best (spec §10).

    ``critical_terms`` (spec §13) are human-labeled entities / error codes /
    constraints that a correct tool query must preserve; used by the
    ``critical_term_preservation_rate`` metric (spec §14).
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
    critical_terms: list[str] = Field(default_factory=list)


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
    critical_terms: list[str] = Field(default_factory=list)
    #: ---- actual run ----
    status: str = "SUCCESS"
    tool_called: bool = False
    no_evidence: bool = False
    actual_sources: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    answer: str = ""
    abstained: bool = False
    #: ---- Layer C: agentic retrieval (primary routing step, spec §7/§21) ----
    routing_steps: list[RoutingStep] = Field(default_factory=list)
    tool_query: str | None = None
    query_rewritten: bool | None = None
    primary_intent: RetrievalIntent | None = None
    primary_strategy: RetrievalStrategy | None = None
    primary_fallback_used: bool = False
    primary_intent_match: bool | None = None
    primary_strategy_match: bool | None = None
    query_rewrite_drift: bool = False
    #: ---- Layer B: router component (filled by merge_router_component) ----
    router_intent_match: bool | None = None
    router_strategy_match: bool | None = None
    router_fallback_used: bool = False
    #: ---- per-dimension verdicts (None = not applicable) ----
    tool_selection_correct: bool | None = None
    source_recall: float | None = None
    answer_matched_terms: list[str] = Field(default_factory=list)
    answer_missing_terms: list[str] = Field(default_factory=list)
    answer_terms_all_present: bool | None = None
    citation_grounded: bool | None = None
    citation_source_recall: float | None = None
    #: ---- query rewrite preservation (spec §13/§14) ----
    critical_terms_preserved: list[str] = Field(default_factory=list)
    critical_terms_missing: list[str] = Field(default_factory=list)
    critical_term_preservation_rate: float | None = None
    #: ---- observability / cost (spec §23/§24) ----
    trace_id: str | None = None
    latency_ms: float | None = None
    model_calls: int | None = None
    tool_call_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    failure_category: FailureCategory | None = None
    failure_message: str | None = None


class MetricSummary(BaseModel):
    """Human-readable aggregate summary (spec §42). None = not computable."""

    sample_count: int = 0
    #: Layer A -- tool selection (Stage 4 core capability, spec §8)
    tool_selection_accuracy: float | None = None
    tool_call_precision: float | None = None
    tool_call_recall: float | None = None
    false_positive_count: int = 0
    false_negative_count: int = 0
    #: Layer B -- router component (spec §3/§21): QueryRouter on the ORIGINAL
    #: dataset query, bypassing the Agent. Measures policy consistency, not
    #: objective retrieval quality.
    router_component_intent_accuracy: float | None = None
    router_component_strategy_accuracy: float | None = None
    router_component_fallback_rate: float | None = None
    #: Layer C -- agentic retrieval (spec §4/§21): primary routing step only.
    primary_intent_accuracy: float | None = None
    primary_strategy_accuracy: float | None = None
    all_routing_steps_count: int = 0
    routing_fallback_rate: float | None = None
    query_rewrite_drift_count: int = 0
    #: retrieval / source coverage (spec §11/§12)
    expected_source_recall: float | None = None
    no_evidence_rate: float | None = None
    #: citation (spec §14/§15)
    citation_grounded_rate: float | None = None
    citation_source_recall: float | None = None
    #: answer / abstention (spec §17/§18)
    answer_term_match_rate: float | None = None
    abstention_accuracy: float | None = None
    #: query rewrite preservation (spec §13/§14)
    critical_term_preservation_rate: float | None = None
    #: latency / tokens / cost (spec §31/§30/§23)
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_tokens: int | None = None
    tokens_per_case: float | None = None
    model_calls_per_case: float | None = None
    tool_calls_per_case: float | None = None
    #: failures (spec §32); NO_EVIDENCE is a business outcome, listed separately
    failure_counts: dict[str, int] = Field(default_factory=dict)
    failed_case_ids: list[str] = Field(default_factory=list)


class RouterComponentResult(BaseModel):
    """Stage 5.1 Layer B: one dataset query routed straight through QueryRouter.

    No Agent, no tool calling, no LLM rewrite (spec §3) -- isolates whether
    QueryRouter itself classifies the *original* user query correctly.
    """

    case_id: str
    query: str
    expected_intent: RetrievalIntent | None = None
    expected_strategy: RetrievalStrategy | None = None
    actual_intent: RetrievalIntent | None = None
    actual_strategy: RetrievalStrategy | None = None
    fallback_used: bool = False
    reason: str = ""
    intent_match: bool | None = None
    strategy_match: bool | None = None


class RouterComponentSummary(BaseModel):
    """Aggregate Layer B metrics (spec §3/§27)."""

    intent_accuracy: float | None = None
    strategy_accuracy: float | None = None
    fallback_rate: float | None = None


class RouterComponentRunResult(BaseModel):
    """One Layer B evaluation pass: per-case decisions + aggregated metrics."""

    run_at: str = ""
    cases: list[RouterComponentResult] = Field(default_factory=list)
    metrics: RouterComponentSummary = Field(default_factory=RouterComponentSummary)


class EvalRunResult(BaseModel):
    """One full evaluation run: dataset meta + cases + metrics."""

    dataset: str = ""
    run_at: str = ""
    sample_count: int = 0
    cases: list[EvalCaseResult] = Field(default_factory=list)
    router_component: RouterComponentRunResult | None = None
    metrics: MetricSummary = Field(default_factory=MetricSummary)
