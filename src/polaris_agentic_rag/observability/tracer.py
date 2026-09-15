"""Tracer -- low-intrusion instrumentation for the Agent path (spec §24, §38).

Design:

- one ``trace_id`` (uuid hex) is created per Agent request and shared by
  Agent -> Tool -> Router -> Adapter via ``TraceContext`` (ContextVar), so
  no business method needs ``tracer/trace_id/sink`` threaded as parameters.
- ``Tracer.emit`` is a no-op when no trace is active, so non-instrumented
  callers (unit fakes) keep working without any tracing setup.
- secret-looking attribute names and chain-of-thought keys are redacted
  before any sink sees them (spec §33, §34).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

from polaris_agentic_rag.observability.models import TraceEvent, TraceEventType
from polaris_agentic_rag.observability.sinks import TraceSink

__all__ = ["ToolCallContext", "TraceContext", "Tracer", "redact_attributes"]

#: attribute names whose value must never reach a sink (secrets, CoT).
#: kept lowercase so an uppercase key (e.g. ``DEEPSEEK_API_KEY``) still
#: matches after ``key.lower()`` comparison.
_REDACT_KEYS = frozenset(
    {
        "api_key",
        "x-api-key",
        "authorization",
        "password",
        "secret",
        "access_token",
        "refresh_token",
        "deepseek_api_key",
        "reasoning_content",
        "reasoning",
        "thinking",
    }
)


def redact_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with secret/chain-of-thought values replaced by a marker."""
    out: dict[str, Any] = {}
    for key, value in attributes.items():
        lowered = str(key).lower()
        if lowered in _REDACT_KEYS or "bearer" in lowered:
            out[key] = "[REDACTED]"
        else:
            out[key] = value
    return out


class TraceContext:
    """ContextVar holding the active ``trace_id`` so nested layers can emit."""

    _var: ContextVar[str | None] = ContextVar("dev_knowledge_trace_id", default=None)

    @classmethod
    def get(cls) -> str | None:
        return cls._var.get()

    @classmethod
    def set(cls, trace_id: str) -> Token[str | None]:
        return cls._var.set(trace_id)

    @classmethod
    def reset(cls, token: Token[str | None]) -> None:
        cls._var.reset(token)


class ToolCallContext:
    """ContextVar holding the tool call id being executed, if any.

    The orchestrator scopes each registry invocation so events emitted by
    the tool itself (ROUTER_DECISION / RETRIEVAL_*) carry the same
    ``tool_call_id`` as TOOL_CALL_STARTED / TOOL_CALL_COMPLETED (spec §20).
    This keeps the correlation without touching the Tool contract.
    """

    _var: ContextVar[str | None] = ContextVar("dev_knowledge_tool_call_id", default=None)

    @classmethod
    def get(cls) -> str | None:
        return cls._var.get()

    @classmethod
    def set(cls, tool_call_id: str) -> Token[str | None]:
        return cls._var.set(tool_call_id)

    @classmethod
    def reset(cls, token: Token[str | None]) -> None:
        cls._var.reset(token)


class Tracer:
    """Emits TraceEvents into the registered sinks for the active trace."""

    def __init__(self, sinks: list[TraceSink] | None = None) -> None:
        self._sinks: list[TraceSink] = list(sinks or [])
        self._sequences: dict[str, int] = {}
        self._token: Token[str | None] | None = None

    def add_sink(self, sink: TraceSink) -> None:
        self._sinks.append(sink)

    def start_trace(self) -> str:
        """Create a trace id and bind it to the current task's context."""
        trace_id = uuid.uuid4().hex
        self._sequences[trace_id] = 0
        self._token = TraceContext.set(trace_id)
        return trace_id

    def end_trace(self) -> None:
        """Unbind the context. Safe to call once per :meth:`start_trace`."""
        if self._token is not None:
            TraceContext.reset(self._token)
            self._token = None

    @contextmanager
    def active_trace(self) -> Iterator[str]:
        """Context-manager form of ``start_trace`` / ``end_trace``."""
        trace_id = self.start_trace()
        try:
            yield trace_id
        finally:
            self.end_trace()

    @property
    def current_tool_call_id(self) -> str | None:
        """Tool call id currently executing (None outside a tool invocation)."""
        return ToolCallContext.get()

    @contextmanager
    def tool_call_scope(self, tool_call_id: str) -> Iterator[None]:
        """Bind ``tool_call_id`` for the duration of one tool invocation.

        Every event emitted inside the scope -- including events from the
        tool itself (ROUTER_DECISION / RETRIEVAL_*) -- can be correlated to
        this tool call without relying on event-list position (spec §20).
        """
        token = ToolCallContext.set(tool_call_id)
        try:
            yield
        finally:
            ToolCallContext.reset(token)

    def emit(
        self,
        event_type: TraceEventType,
        *,
        trace_id: str | None = None,
        ts_ms: float | None = None,
        **attributes: Any,
    ) -> TraceEvent | None:
        """Emit one event to every sink.

        Returns ``None`` (no event) when no trace is active and no explicit
        ``trace_id`` is given -- instrumentation in fakes stays harmless.
        """
        tid = trace_id or TraceContext.get()
        if tid is None:
            return None
        seq = self._sequences.get(tid, 0)
        self._sequences[tid] = seq + 1
        event = TraceEvent(
            trace_id=tid,
            event_type=event_type,
            seq=seq,
            ts_ms=ts_ms if ts_ms is not None else time.time() * 1000.0,
            attributes=redact_attributes(dict(attributes)),
        )
        for sink in self._sinks:
            sink.accept(event)
        return event

    @contextmanager
    def span(
        self,
        start: TraceEventType,
        complete: TraceEventType,
        *,
        trace_id: str | None = None,
        **attributes: Any,
    ) -> Iterator[None]:
        """Emit ``start``, yield, then emit ``complete`` with ``duration_ms``."""
        t0 = time.perf_counter()
        self.emit(start, trace_id=trace_id, **attributes)
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            self.emit(
                complete,
                trace_id=trace_id,
                duration_ms=round(duration_ms, 3),
                **attributes,
            )
