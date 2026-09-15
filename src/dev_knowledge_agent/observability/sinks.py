"""TraceSink abstraction + two concrete sinks (spec §35-37).

Core observability never ``print()``s; everything flows through a
``TraceSink``. ``InMemoryTraceSink`` is for offline tests and evaluation;
``JsonlTraceSink`` appends one JSON object per event under
``.local/traces/`` (gitignored). No database, no external tracing backend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from dev_knowledge_agent.observability.models import TraceEvent, TraceEventType

__all__ = ["TraceSink", "InMemoryTraceSink", "JsonlTraceSink"]


@runtime_checkable
class TraceSink(Protocol):
    """Receives serialisable trace events."""

    def accept(self, event: TraceEvent) -> None:
        """Consume one trace event (implementations must never raise into the app)."""
        ...


class InMemoryTraceSink:
    """Collects events in memory for assertions / evaluation (§36)."""

    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    def accept(self, event: TraceEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> list[TraceEvent]:
        return list(self._events)

    def events_of(self, event_type: TraceEventType) -> list[TraceEvent]:
        return [e for e in self._events if e.event_type is event_type]

    def has(self, event_type: TraceEventType) -> bool:
        return any(e.event_type is event_type for e in self._events)

    def clear(self) -> None:
        self._events.clear()


class JsonlTraceSink:
    """Appends one JSON line per event under ``directory/<trace_id>.jsonl`` (§37)."""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)

    def accept(self, event: TraceEvent) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        line = event.model_dump_json()
        with (self._directory / f"{event.trace_id}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
