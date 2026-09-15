"""Observability domain model (Stage 5) -- framework/provider-neutral.

``TraceEvent`` / ``TraceEventType`` / ``FailureCategory`` are OUR types.
They never import a provider SDK (``openai`` / DeepSeek) or LightRAG
(architecture guard). Sinks serialise them, ``tracer.py`` emits them; the
contract is deliberately small so a future OpenTelemetry / Langfuse /
LangSmith sink adapter can be written without touching the rest of the
system (spec §39).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

__all__ = [
    "Trace",
    "TraceEvent",
    "TraceEventType",
    "FailureCategory",
]


class TraceEventType(str, Enum):
    """Lifecycle events one Agent request can emit (spec §25).

    Event names are application-owned; a future external backend may map
    them onto its own vocabulary. We never store chain-of-thought or hidden
    reasoning content (spec §34).
    """

    AGENT_STARTED = "AGENT_STARTED"
    MODEL_CALL_STARTED = "MODEL_CALL_STARTED"
    MODEL_CALL_COMPLETED = "MODEL_CALL_COMPLETED"
    TOOL_SELECTED = "TOOL_SELECTED"
    TOOL_CALL_STARTED = "TOOL_CALL_STARTED"
    TOOL_CALL_COMPLETED = "TOOL_CALL_COMPLETED"
    ROUTER_DECISION = "ROUTER_DECISION"
    RETRIEVAL_STARTED = "RETRIEVAL_STARTED"
    RETRIEVAL_COMPLETED = "RETRIEVAL_COMPLETED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    ERROR = "ERROR"


class FailureCategory(str, Enum):
    """Application-level failure taxonomy (spec §32).

    ``NO_EVIDENCE`` is a *normal business outcome* (honest abstention), not a
    system error -- evaluation must not lump it in with the ERROR categories.
    ``QUERY_REWRITE_INTENT_DRIFT`` (Stage 5.1): the Router routes the *original*
    user query correctly, but the Agent's rewritten tool query loses the
    retrieval signal -- this is an Agent -> tool-query interface problem, NOT a
    Router failure. ``EVALUATION_AGGREGATION_ERROR`` guards the evaluation
    harness itself: after the Stage 5.1 routing-step fix, a real run must
    never produce one (spec §19).
    """

    MODEL_ERROR = "MODEL_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    MAX_STEPS = "MAX_STEPS"
    MAX_TOOL_CALLS = "MAX_TOOL_CALLS"
    NO_EVIDENCE = "NO_EVIDENCE"
    ROUTING_FALLBACK = "ROUTING_FALLBACK"
    RETRIEVAL_ERROR = "RETRIEVAL_ERROR"
    CITATION_ERROR = "CITATION_ERROR"
    QUERY_REWRITE_INTENT_DRIFT = "QUERY_REWRITE_INTENT_DRIFT"
    EVALUATION_AGGREGATION_ERROR = "EVALUATION_AGGREGATION_ERROR"


class TraceEvent(BaseModel):
    """One structured event of a request trace.

    ``attributes`` are flat key/value data (latency, counts, status, ...).
    The ``Tracer`` redacts secret-looking keys and never receives
    chain-of-thought, so nothing sensitive reaches the sinks.
    """

    trace_id: str
    event_type: TraceEventType
    seq: int = 0
    ts_ms: float = 0.0
    attributes: dict[str, object] = Field(default_factory=dict)


class Trace(BaseModel):
    """A complete, in-memory request trace (``trace_id`` + ordered events)."""

    trace_id: str
    events: list[TraceEvent] = Field(default_factory=list)
