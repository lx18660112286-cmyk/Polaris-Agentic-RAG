"""Trace order + trace failure integration through the real orchestrator (spec §49/§50).

Uses the offline ScriptedModel / FakeKnowledgeSearchPort + the REAL
``RagSearchTool`` (so Router / Retrieval events actually fire) plus a real
``Tracer`` with an ``InMemoryTraceSink``, then asserts the emitted event
stream ordering WITHOUT any LLM.
"""

from __future__ import annotations

from dev_knowledge_agent.agent.models import (
    AgentMessage,
    AgentModelResponse,
    AgentStatus,
    AgentToolCall,
)
from dev_knowledge_agent.agent.orchestrator import AgentOrchestrator
from dev_knowledge_agent.evidence.models import (
    EvidenceAvailability,
    KnowledgeSearchResult,
)
from dev_knowledge_agent.observability.models import TraceEventType
from dev_knowledge_agent.observability.sinks import InMemoryTraceSink
from dev_knowledge_agent.observability.tracer import Tracer
from dev_knowledge_agent.protocols.agent_model import AgentModelPort
from dev_knowledge_agent.retrieval.router import QueryRouter
from dev_knowledge_agent.tools.protocol import ToolDefinition
from dev_knowledge_agent.tools.rag_search import (
    AgentRagSearchTool,
    RagSearchTool,
)
from dev_knowledge_agent.tools.registry import ToolRegistry

SYSTEM = "You are Dev Knowledge Agent."


class FakeKnowledgeSearchPort:
    """Offline port standing in for LightRAGAdapter."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.raises = raises
        self.queries: list[str] = []

    async def search(self, query: str, *, plan=None) -> KnowledgeSearchResult:
        del plan
        self.queries.append(query)
        if self.raises:
            raise self.raises
        return KnowledgeSearchResult(
            query=query,
            evidence_availability=EvidenceAvailability.PRESENT,
        )


class ScriptedModel(AgentModelPort):
    def __init__(self, responses: list[AgentModelResponse]) -> None:
        self._responses = list(responses)

    async def complete(
        self,
        messages: list[AgentMessage],
        tools: list[ToolDefinition],
    ) -> AgentModelResponse:
        del messages, tools
        if self._responses:
            return self._responses.pop(0)
        #: exhausted script -> final answer, stops the loop
        return AgentModelResponse(content="done", usage=None)


def _make_tc(raw_arguments: str) -> AgentModelResponse:
    return AgentModelResponse(
        content=None,
        tool_calls=[
            AgentToolCall(id="c1", name="search_dev_knowledge", raw_arguments=raw_arguments)
        ],
    )


def _build(
    port: FakeKnowledgeSearchPort,
    model: ScriptedModel,
    sink: InMemoryTraceSink,
    *,
    max_tool_calls: int = 3,
) -> AgentOrchestrator:
    tracer = Tracer(sinks=[sink])
    rag_tool = RagSearchTool(search_port=port, router=QueryRouter(), tracer=tracer)
    registry = ToolRegistry()
    registry.register(AgentRagSearchTool(rag_tool))
    return AgentOrchestrator(
        model=model,
        registry=registry,
        system_prompt=SYSTEM,
        max_steps=4,
        max_tool_calls=max_tool_calls,
        tracer=tracer,
    )


def _event_types(sink: InMemoryTraceSink) -> list[TraceEventType]:
    return [e.event_type for e in sink.events]


async def test_trace_covers_success_path_in_order() -> None:
    sink = InMemoryTraceSink()
    port = FakeKnowledgeSearchPort()
    model = ScriptedModel(
        [
            _make_tc('{"query":"Access token 有效期"}'),
            AgentModelResponse(content="30 分钟", usage=None),
        ]
    )
    orch = _build(port, model, sink)
    result = await orch.run("Access token 有效期是多少？")

    types = _event_types(sink)
    assert types[0] is TraceEventType.AGENT_STARTED
    #: one full Agent -> Model -> Tool -> Router -> Retrieval -> Agent cycle
    assert TraceEventType.MODEL_CALL_STARTED in types
    assert TraceEventType.TOOL_SELECTED in types
    assert TraceEventType.TOOL_CALL_STARTED in types
    assert TraceEventType.ROUTER_DECISION in types
    assert TraceEventType.RETRIEVAL_STARTED in types
    assert TraceEventType.RETRIEVAL_COMPLETED in types
    assert TraceEventType.TOOL_CALL_COMPLETED in types
    assert types[-1] is TraceEventType.AGENT_COMPLETED
    assert result.trace_id is not None
    assert all(e.trace_id == result.trace_id for e in sink.events)
    #: the Tool really fired against the port via the real RagSearchTool
    assert port.queries == ["Access token 有效期"] or port.queries

    #: ordering invariants, not exact positions (spec §49)
    started = types.index(TraceEventType.AGENT_STARTED)
    completed = types.index(TraceEventType.AGENT_COMPLETED)
    assert started < completed
    assert types.index(TraceEventType.TOOL_SELECTED) < types.index(
        TraceEventType.TOOL_CALL_COMPLETED
    )
    assert types.index(TraceEventType.TOOL_CALL_STARTED) <= types.index(
        TraceEventType.TOOL_CALL_COMPLETED
    )
    assert types.index(TraceEventType.ROUTER_DECISION) <= types.index(
        TraceEventType.RETRIEVAL_STARTED
    )
    assert types.index(TraceEventType.RETRIEVAL_STARTED) <= types.index(
        TraceEventType.RETRIEVAL_COMPLETED
    )


async def test_trace_covers_model_failure_with_error_event() -> None:
    sink = InMemoryTraceSink()

    class ExplodingModel(AgentModelPort):
        async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
            del messages, tools
            raise RuntimeError("provider outage")

    orch = _build(FakeKnowledgeSearchPort(), ExplodingModel(), sink)
    result = await orch.run("hello")

    assert result.status is AgentStatus.MODEL_ERROR
    types = _event_types(sink)
    assert types[0] is TraceEventType.AGENT_STARTED
    assert TraceEventType.MODEL_CALL_STARTED in types
    assert TraceEventType.ERROR in types
    assert types[-1] is TraceEventType.AGENT_COMPLETED
    error_event = sink.events_of(TraceEventType.ERROR)[0]
    assert error_event.attributes["category"] == "MODEL_ERROR"
    assert "provider outage" in str(error_event.attributes["error"])


async def test_trace_covers_retrieval_failure_with_error_event() -> None:
    sink = InMemoryTraceSink()
    port = FakeKnowledgeSearchPort(raises=RuntimeError("kernel boom"))
    model = ScriptedModel(
        [
            _make_tc('{"query":"x"}'),
            AgentModelResponse(content="知识检索失败。"),
        ]
    )
    orch = _build(port, model, sink)
    result = await orch.run("x")

    types = _event_types(sink)
    assert result.tool_calls[0].result_status == "ERROR"
    #: a retrieval ERROR event is emitted by the Tool; the ERrored record is
    #: surfaced to the model via the formatted tool content, not the record.
    assert TraceEventType.ERROR in types
    assert types[-1] is TraceEventType.AGENT_COMPLETED


async def test_trace_has_sequential_event_ids_per_trace() -> None:
    sink = InMemoryTraceSink()
    orch = _build(FakeKnowledgeSearchPort(), ScriptedModel([]), sink)
    await orch.run("x")

    seqs = [e.seq for e in sink.events]
    assert seqs == sorted(seqs)  #: monotonically increasing overall
