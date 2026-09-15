"""Observability & tracing (Stage 5).

Structured ``TraceEvent`` contract (spec §23) plus a ``TraceSink``
abstraction. The core never imports a provider SDK or LightRAG
(architecture guard): provider adapters map raw usage onto our events at
the boundary (spec §59).
"""

from __future__ import annotations

from polaris_agentic_rag.observability.analysis import (
    agent_latency_ms,
    events_of,
    has_event,
    last_attribute,
    sum_attributes,
)
from polaris_agentic_rag.observability.models import (
    FailureCategory,
    Trace,
    TraceEvent,
    TraceEventType,
)
from polaris_agentic_rag.observability.sinks import (
    InMemoryTraceSink,
    JsonlTraceSink,
    TraceSink,
)
from polaris_agentic_rag.observability.tracer import TraceContext, Tracer

__all__ = [
    "FailureCategory",
    "InMemoryTraceSink",
    "JsonlTraceSink",
    "Trace",
    "TraceContext",
    "TraceEvent",
    "TraceEventType",
    "TraceSink",
    "Tracer",
    "agent_latency_ms",
    "events_of",
    "has_event",
    "last_attribute",
    "sum_attributes",
]
