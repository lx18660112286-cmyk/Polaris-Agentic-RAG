"""Offline tests for the trace event contract + redaction (spec §23/§33/§34)."""

from __future__ import annotations

from polaris_agentic_rag.observability.models import (
    Trace,
    TraceEvent,
    TraceEventType,
)
from polaris_agentic_rag.observability.sinks import InMemoryTraceSink
from polaris_agentic_rag.observability.tracer import Tracer, redact_attributes


def test_trace_event_serializes_to_json() -> None:
    event = TraceEvent(
        trace_id="abc",
        event_type=TraceEventType.ROUTER_DECISION,
        seq=2,
        ts_ms=123.4,
        attributes={"intent": "factual", "fallback_used": True},
    )
    dumped = event.model_dump_json()
    assert '"ROUTER_DECISION"' in dumped
    assert '"intent":"factual"' in dumped.replace(" ", "")


def test_trace_collects_events_in_order() -> None:
    trace = Trace(trace_id="t1")
    trace.events.append(TraceEvent(trace_id="t1", event_type=TraceEventType.AGENT_STARTED))
    trace.events.append(TraceEvent(trace_id="t1", event_type=TraceEventType.AGENT_COMPLETED))
    assert [e.event_type for e in trace.events] == [
        TraceEventType.AGENT_STARTED,
        TraceEventType.AGENT_COMPLETED,
    ]


def test_redact_attributes_removes_secrets() -> None:
    redacted = redact_attributes(
        {
            "api_key": "sk-123",
            "authorization": "Bearer abc",
            "query": "hello",
            "DEEPSEEK_API_KEY": "sk-secret",
            "reasoning_content": "hidden chain of thought",
        }
    )
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["DEEPSEEK_API_KEY"] == "[REDACTED]"
    assert "chain of thought" not in str(redacted)
    assert redacted["query"] == "hello"


def test_bearer_in_key_name_is_redacted() -> None:
    redacted = redact_attributes({"x-my-bearer-token": "tok"})
    assert redacted["x-my-bearer-token"] == "[REDACTED]"


def test_no_trace_is_emitted_without_active_trace() -> None:
    tracer = Tracer()
    event = tracer.emit(TraceEventType.AGENT_STARTED, query="x")
    assert event is None


def test_trace_id_and_seq_are_monotonic() -> None:
    sink = InMemoryTraceSink()
    tracer = Tracer(sinks=[sink])
    trace_id = tracer.start_trace()
    try:
        alpha = tracer.emit(TraceEventType.AGENT_STARTED)
        beta = tracer.emit(TraceEventType.AGENT_COMPLETED)
        assert alpha.trace_id == trace_id  # type: ignore[union-attr]
        assert beta.trace_id == trace_id  # type: ignore[union-attr]
        assert beta.seq == alpha.seq + 1  # type: ignore[union-attr]
    finally:
        tracer.end_trace()


def test_active_trace_context_manager() -> None:
    sink = InMemoryTraceSink()
    tracer = Tracer(sinks=[sink])
    with tracer.active_trace() as trace_id:
        event = tracer.emit(TraceEventType.ERROR, category="MODEL_ERROR")
        assert event is not None
        assert event.trace_id == trace_id


def test_span_emits_start_and_complete_with_duration() -> None:
    sink = InMemoryTraceSink()
    tracer = Tracer(sinks=[sink])
    tracer.start_trace()
    try:
        with tracer.span(
            TraceEventType.TOOL_CALL_STARTED,
            TraceEventType.TOOL_CALL_COMPLETED,
            name="search_dev_knowledge",
        ):
            pass  #: simulated work
        events = sink.events_of(TraceEventType.TOOL_CALL_COMPLETED)
        assert len(events) == 1
        assert events[0].attributes.get("name") == "search_dev_knowledge"
        assert isinstance(events[0].attributes.get("duration_ms"), (int, float))
    finally:
        tracer.end_trace()
