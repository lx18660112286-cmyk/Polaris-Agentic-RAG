"""Unit tests for ToolRegistry (provider-neutral, offline)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from polaris_agentic_rag.tools.errors import (
    DuplicateToolError,
    InvalidToolArgumentsError,
    UnknownToolError,
)
from polaris_agentic_rag.tools.protocol import AgentTool, ToolDefinition
from polaris_agentic_rag.tools.registry import ToolRegistry


class EchoInput(BaseModel):
    query: str


class EchoTool:
    """A minimal fake AgentTool that echoes (keeps invocation count)."""

    name = "echo"
    description = "echo the query back"

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def input_schema(self) -> type[BaseModel]:
        return EchoInput

    async def invoke(self, input_: BaseModel) -> str:
        assert isinstance(input_, EchoInput)
        self.calls.append(input_.query)
        return f"echo:{input_.query}"


def _make_registry(tool: EchoTool | None = None) -> tuple[ToolRegistry, EchoTool]:
    registry = ToolRegistry()
    t = tool or EchoTool()
    registry.register(t)
    return registry, t


def test_register_and_get() -> None:
    registry, tool = _make_registry()
    assert registry.get("echo") is tool
    assert registry.tool_names == ["echo"]


def test_duplicate_registration_raises() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    with pytest.raises(DuplicateToolError):
        registry.register(EchoTool())


def test_unknown_tool_raises() -> None:
    registry, _ = _make_registry()
    with pytest.raises(UnknownToolError):
        registry.get("does_not_exist")


def test_unknown_tool_invoke_raises() -> None:
    registry, _ = _make_registry()
    with pytest.raises(UnknownToolError):
        import asyncio

        asyncio.run(registry.invoke("delete_production_database", "{}"))


def test_definitions_derive_schema_from_input_model() -> None:
    registry, _ = _make_registry()
    defs = registry.definitions()
    assert len(defs) == 1
    td = defs[0]
    assert isinstance(td, ToolDefinition)
    assert td.name == "echo"
    assert td.parameters is EchoInput
    schema = EchoInput.model_json_schema()
    assert "query" in schema["properties"]


def test_valid_invocation() -> None:
    registry, tool = _make_registry()
    import asyncio

    result = asyncio.run(registry.invoke("echo", '{"query": "hi"}'))
    assert result.ok is True
    assert result.value == "echo:hi"
    assert tool.calls == ["hi"]


def test_malformed_json_raises() -> None:
    registry, _ = _make_registry()
    import asyncio

    with pytest.raises(InvalidToolArgumentsError):
        asyncio.run(registry.invoke("echo", "{not json"))


def test_empty_arguments_raises() -> None:
    registry, _ = _make_registry()
    import asyncio

    with pytest.raises(InvalidToolArgumentsError):
        asyncio.run(registry.invoke("echo", ""))


def test_missing_required_field_raises() -> None:
    registry, _ = _make_registry()
    import asyncio

    with pytest.raises(InvalidToolArgumentsError):
        asyncio.run(registry.invoke("echo", "{}"))


def test_unknown_extra_field_strictness() -> None:
    """Extra unknown fields are handled by Pydantic extra=ignore only if allowed;
    otherwise they fail validation. EchoInput has no config, so extra is ignored
    by Pydantic default -- the call still succeeds."""

    class StrictInput(BaseModel):
        query: str
        model_config = {"extra": "forbid"}

    class StrictTool:
        name = "strict"
        description = "strict"

        @property
        def input_schema(self) -> type[BaseModel]:
            return StrictInput

        async def invoke(self, input_: BaseModel) -> str:
            return input_.query  # type: ignore[no-any-return]

    registry = ToolRegistry()
    registry.register(StrictTool())
    import asyncio

    with pytest.raises(InvalidToolArgumentsError):
        asyncio.run(registry.invoke("strict", '{"query": "x", "nope": 1}'))


def test_agent_tool_protocol_is_structural() -> None:
    tool = EchoTool()
    assert isinstance(tool, AgentTool)
