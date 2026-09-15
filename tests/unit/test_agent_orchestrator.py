"""Unit tests for AgentOrchestrator (offline, FakeAgentModel + FakeTool)."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from polaris_agentic_rag.agent.models import (
    AgentMessage,
    AgentModelResponse,
    AgentRole,
    AgentStatus,
    AgentToolCall,
)
from polaris_agentic_rag.agent.orchestrator import AgentOrchestrator
from polaris_agentic_rag.protocols.agent_model import AgentModelPort
from polaris_agentic_rag.tools.protocol import ToolDefinition
from polaris_agentic_rag.tools.registry import ToolRegistry

SYSTEM = "You are Dev Knowledge Agent."


class RagInput(BaseModel):
    query: str


class FakeRagResult:
    """Duck-typed RagSearchResult-lookalike for the formatter."""

    def __init__(self, status: str, citations=(), error=None) -> None:
        self.status = status
        self.query = "q"
        self.citations = [SimpleNamespace(source_name=c) for c in citations]
        self.error = error
        self.evidence = SimpleNamespace(chunks=[0], entities=[0], relationships=[0])


class FakeRagTool:
    name = "search_dev_knowledge"
    description = "search internal knowledge"

    def __init__(
        self, result: FakeRagResult | None = None, raises: Exception | None = None
    ) -> None:
        self.result = result or FakeRagResult("SUCCESS", citations=["api_auth.md"])
        self.raises = raises
        self.calls: list[str] = []

    @property
    def input_schema(self) -> type[BaseModel]:
        return RagInput

    async def invoke(self, input_: BaseModel) -> FakeRagResult:
        assert isinstance(input_, RagInput)
        self.calls.append(input_.query)
        if self.raises:
            raise self.raises
        return self.result


class ScriptedModel(AgentModelPort):
    """Returns a scripted sequence of responses; records received messages."""

    def __init__(self, responses: list[AgentModelResponse], fail_on: int | None = None) -> None:
        self._responses = list(responses)
        self._fail_on = fail_on
        self._count = 0
        self.seen_messages: list[list[AgentMessage]] = []
        self.seen_tools: list[list[ToolDefinition]] = []

    async def complete(
        self,
        messages: list[AgentMessage],
        tools: list[ToolDefinition],
    ) -> AgentModelResponse:
        self._count += 1
        self.seen_messages.append(list(messages))
        self.seen_tools.append(tools)
        if self._fail_on is not None and self._count == self._fail_on:
            raise RuntimeError("model exploded")
        if self._responses:
            return self._responses.pop(0)
        #: never-ending tool calls
        return AgentModelResponse(
            content=None,
            tool_calls=[
                AgentToolCall(
                    id=f"c{self._count}", name="search_dev_knowledge", raw_arguments='{"query":"x"}'
                )
            ],
        )


def _make_tc(name: str, raw: str, call_id: str = "c1") -> AgentModelResponse:
    return AgentModelResponse(
        content=None,
        tool_calls=[AgentToolCall(id=call_id, name=name, raw_arguments=raw)],
    )


def _build(
    tool: FakeRagTool,
    model: ScriptedModel,
    *,
    max_steps: int = 4,
    max_tool_calls: int = 3,
) -> AgentOrchestrator:
    registry = ToolRegistry()
    registry.register(tool)
    return AgentOrchestrator(
        model=model,
        registry=registry,
        system_prompt=SYSTEM,
        max_steps=max_steps,
        max_tool_calls=max_tool_calls,
    )


async def test_direct_answer_path() -> None:
    model = ScriptedModel([AgentModelResponse(content="Hi there")])
    orch = _build(FakeRagTool(), model)
    result = await orch.run("你好")
    assert result.status is AgentStatus.SUCCESS
    assert result.answer == "Hi there"
    assert result.tool_calls == []
    assert result.steps == 1


async def test_calls_tool_then_final_answer() -> None:
    tool = FakeRagTool(result=FakeRagResult("SUCCESS", citations=["api_auth.md"]))
    model = ScriptedModel(
        [
            _make_tc("search_dev_knowledge", '{"query":"Access token 的有效期是多少？"}'),
            AgentModelResponse(content="30 分钟"),
        ]
    )
    orch = _build(tool, model)
    result = await orch.run("Access token 的有效期是多少？")
    assert result.status is AgentStatus.SUCCESS
    assert tool.calls == ["Access token 的有效期是多少？"]
    assert result.answer == "30 分钟"
    assert result.citations == ["api_auth.md"]
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "search_dev_knowledge"
    assert result.tool_calls[0].result_status == "SUCCESS"


async def test_no_evidence_surface_and_status() -> None:
    tool = FakeRagTool(result=FakeRagResult("NO_EVIDENCE", citations=[]))
    model = ScriptedModel(
        [
            _make_tc("search_dev_knowledge", '{"query":"Billing Service 使用什么数据库？"}'),
            AgentModelResponse(content="知识库没有足够信息。"),
        ]
    )
    orch = _build(tool, model)
    result = await orch.run("Billing Service 使用什么数据库？")
    assert result.status is AgentStatus.SUCCESS
    assert result.tool_calls[0].result_status == "NO_EVIDENCE"
    assert result.citations == []


async def test_tool_error_does_not_crash_and_is_recorded() -> None:
    tool = FakeRagTool(raises=RuntimeError("kernel boom"))
    model = ScriptedModel(
        [
            _make_tc("search_dev_knowledge", '{"query":"x"}'),
            AgentModelResponse(content="知识检索暂时失败。"),
        ]
    )
    orch = _build(tool, model)
    result = await orch.run("x")
    assert result.status is AgentStatus.SUCCESS
    rec = result.tool_calls[0]
    assert rec.result_status == "error"
    assert "kernel boom" in (rec.error or "")


async def test_unknown_tool_rejected() -> None:
    tool = FakeRagTool()
    model = ScriptedModel(
        [
            _make_tc("delete_production_database", "{}"),
            AgentModelResponse(content="没有这个工具。"),
        ]
    )
    orch = _build(tool, model)
    result = await orch.run("x")
    assert result.status is AgentStatus.SUCCESS
    rec = result.tool_calls[0]
    assert rec.result_status == "unknown_tool"


async def test_invalid_json_arguments_rejected() -> None:
    tool = FakeRagTool()
    model = ScriptedModel(
        [
            _make_tc("search_dev_knowledge", "{bad json"),
            AgentModelResponse(content="参数错误。"),
        ]
    )
    orch = _build(tool, model)
    result = await orch.run("x")
    assert result.status is AgentStatus.SUCCESS
    assert result.tool_calls[0].result_status == "invalid_arguments"


async def test_schema_validation_failure_rejected() -> None:
    tool = FakeRagTool()
    model = ScriptedModel(
        [
            _make_tc("search_dev_knowledge", "{}"),  # missing query
            AgentModelResponse(content="参数缺失。"),
        ]
    )
    orch = _build(tool, model)
    result = await orch.run("x")
    assert result.tool_calls[0].result_status == "invalid_arguments"


async def test_duplicate_tool_call_rejected() -> None:
    tool = FakeRagTool()
    model = ScriptedModel(
        [
            _make_tc("search_dev_knowledge", '{"query":"same"}', call_id="c1"),
            _make_tc("search_dev_knowledge", '{"query":"same"}', call_id="c2"),
            AgentModelResponse(content="done"),
        ]
    )
    orch = _build(tool, model)
    result = await orch.run("x")
    assert result.status is AgentStatus.SUCCESS
    assert result.tool_calls[0].result_status == "SUCCESS"
    assert result.tool_calls[1].result_status == "duplicate"
    #: the duplicate was not executed -> only one real call
    assert tool.calls == ["same"]


async def test_max_steps_exceeded() -> None:
    tool = FakeRagTool()
    #: empty script -> model returns an endless tool call (Runner stops below)
    model = ScriptedModel([])
    orch = _build(tool, model, max_steps=2, max_tool_calls=10)
    result = await orch.run("x")
    assert result.status is AgentStatus.MAX_STEPS_EXCEEDED
    assert result.steps == 3  #: looped past max_steps=2


async def test_max_tool_calls_exceeded() -> None:
    tool = FakeRagTool()
    model = ScriptedModel([])
    orch = _build(tool, model, max_steps=10, max_tool_calls=2)
    result = await orch.run("x")
    assert result.status is AgentStatus.TOOL_ERROR


async def test_model_error_mapped() -> None:
    tool = FakeRagTool()
    model = ScriptedModel([], fail_on=1)
    orch = _build(tool, model)
    result = await orch.run("x")
    assert result.status is AgentStatus.MODEL_ERROR


async def test_system_prompt_is_sent_first() -> None:
    tool = FakeRagTool()
    model = ScriptedModel([AgentModelResponse(content="hi")])
    orch = _build(tool, model)
    await orch.run("hello")
    first_messages = model.seen_messages[0]
    assert first_messages[0].role is AgentRole.SYSTEM
    assert first_messages[0].content == SYSTEM
    assert first_messages[1].role is AgentRole.USER
