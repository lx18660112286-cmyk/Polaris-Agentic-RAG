"""Pure helpers to read a completed trace (used by evaluation).

These only read ``TraceEvent`` objects -- no I/O, no provider imports, no
LightRAG / OpenAI dependency (architecture guard).
"""

from __future__ import annotations

from typing import Any

from polaris_agentic_rag.observability.models import TraceEvent, TraceEventType

__all__ = [
    "agent_latency_ms",
    "events_of",
    "has_event",
    "last_attribute",
    "sum_attributes",
]


def events_of(events: list[TraceEvent], event_type: TraceEventType) -> list[TraceEvent]:
    """All events of the given type, in emission order."""
    return [e for e in events if e.event_type is event_type]


def has_event(events: list[TraceEvent], event_type: TraceEventType) -> bool:
    return any(e.event_type is event_type for e in events)


def agent_latency_ms(events: list[TraceEvent]) -> float | None:
    """Wall-clock span between AGENT_STARTED and AGENT_COMPLETED (spec §31)."""
    started = events_of(events, TraceEventType.AGENT_STARTED)
    completed = events_of(events, TraceEventType.AGENT_COMPLETED)
    if not started or not completed:
        return None
    return round(completed[-1].ts_ms - started[0].ts_ms, 3)


def sum_attributes(events: list[TraceEvent], event_type: TraceEventType, key: str) -> int:
    """Sum a numeric attribute (int/float only) over events of one type."""
    total = 0
    for e in events_of(events, event_type):
        value = e.attributes.get(key)
        if isinstance(value, (int, float)):
            total += int(value)
    return total


def last_attribute(events: list[TraceEvent], event_type: TraceEventType, key: str) -> Any | None:
    """Value of the last event of a type that carries ``key`` (else None)."""
    for e in reversed(events_of(events, event_type)):
        if key in e.attributes:
            return e.attributes[key]
    return None
