"""Offline tests for TraceSink implementations (spec §35-37)."""

from __future__ import annotations

import json

from polaris_agentic_rag.observability.models import (
    TraceEvent,
    TraceEventType,
)
from polaris_agentic_rag.observability.sinks import (
    InMemoryTraceSink,
    JsonlTraceSink,
)
from polaris_agentic_rag.observability.tracer import Tracer


def test_in_memory_sink_collects_events() -> None:
    sink = InMemoryTraceSink()
    tracer = Tracer(sinks=[sink])
    trace_id = tracer.start_trace()
    try:
        tracer.emit(TraceEventType.AGENT_STARTED, query="q1")
        tracer.emit(TraceEventType.MODEL_CALL_STARTED, step=1)
        tracer.emit(TraceEventType.AGENT_COMPLETED, status="SUCCESS")
    finally:
        tracer.end_trace()

    assert len(sink.events) == 3
    assert sink.has(TraceEventType.AGENT_STARTED)
    assert [e.trace_id for e in sink.events] == [trace_id] * 3


def test_in_memory_sink_events_of_and_clear() -> None:
    sink = InMemoryTraceSink()
    tracer = Tracer(sinks=[sink])
    tracer.start_trace()
    try:
        tracer.emit(TraceEventType.ERROR, category="MAX_STEPS")
        tracer.emit(TraceEventType.ERROR, category="MODEL_ERROR")
        tracer.emit(TraceEventType.MODEL_CALL_COMPLETED, latency_ms=1.0)
    finally:
        tracer.end_trace()

    errors = sink.events_of(TraceEventType.ERROR)
    assert len(errors) == 2
    assert [e.attributes["category"] for e in errors] == ["MAX_STEPS", "MODEL_ERROR"]
    sink.clear()
    assert sink.events == []


def test_jsonl_sink_writes_one_line_per_event(tmp_path) -> None:
    sink = JsonlTraceSink(directory=tmp_path / "traces")
    tracer = Tracer(sinks=[sink])
    trace_id = tracer.start_trace()
    try:
        tracer.emit(TraceEventType.AGENT_STARTED, query="hello")
        tracer.emit(TraceEventType.AGENT_COMPLETED, status="SUCCESS")
    finally:
        tracer.end_trace()

    trace_file = tmp_path / "traces" / f"{trace_id}.jsonl"
    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["trace_id"] == trace_id
    assert first["event_type"] == "AGENT_STARTED"


def test_jsonl_sink_redacts_secrets_on_disk(tmp_path) -> None:
    sink = JsonlTraceSink(directory=tmp_path / "traces")
    tracer = Tracer(sinks=[sink])
    trace_id = tracer.start_trace()
    try:
        tracer.emit(
            TraceEventType.ERROR,
            category="MODEL_ERROR",
            DEEPSEEK_API_KEY="sk-super-secret",
            reason="response invalid",
        )
    finally:
        tracer.end_trace()

    content = (tmp_path / "traces" / f"{trace_id}.jsonl").read_text(encoding="utf-8")
    assert "sk-super-secret" not in content
    assert "REDACTED" in content


def test_sink_never_receives_chain_of_thought() -> None:
    from polaris_agentic_rag.observability.tracer import redact_attributes

    sanitized = redact_attributes({"reasoning_content": "model secret thoughts"})
    TraceEvent(
        trace_id="t",
        event_type=TraceEventType.MODEL_CALL_COMPLETED,
        attributes=sanitized,
    )
    assert sanitized["reasoning_content"] == "[REDACTED]"
    assert "secret thoughts" not in str(sanitized)


def test_span_emits_start_and_complete_with_duration() -> None:
    sink = InMemoryTraceSink()
    tracer = Tracer(sinks=[sink])
    trace_id = tracer.start_trace()
    try:
        with tracer.span(
            TraceEventType.TOOL_CALL_STARTED,
            TraceEventType.TOOL_CALL_COMPLETED,
            name="search",
        ):
            pass
        completed = sink.events_of(TraceEventType.TOOL_CALL_COMPLETED)
        assert len(completed) == 1
        assert completed[0].attributes["name"] == "search"
        assert isinstance(completed[0].attributes["duration_ms"], (int, float))
        #: the span context is the active trace
        assert completed[0].trace_id == trace_id
    finally:
        tracer.end_trace()
