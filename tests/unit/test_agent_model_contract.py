"""Contract tests for AgentModelPort."""

from __future__ import annotations

import inspect
from typing import get_type_hints

from dev_knowledge_agent.agent.models import (
    AgentMessage,
    AgentModelResponse,
    AgentToolCall,
)
from dev_knowledge_agent.protocols.agent_model import AgentModelPort
from dev_knowledge_agent.tools.protocol import ToolDefinition


class FakeAgentModel:
    """A provider-neutral model port (no openai anywhere)."""

    async def complete(
        self,
        messages: list[AgentMessage],
        tools: list[ToolDefinition],
    ) -> AgentModelResponse:
        return AgentModelResponse(content="hi")


def test_fake_satisfies_port_contract() -> None:
    model: AgentModelPort = FakeAgentModel()  # type: ignore[type-abstract]
    assert isinstance(model, AgentModelPort)


def test_port_signature_is_provider_neutral() -> None:
    sig = inspect.signature(AgentModelPort.complete)
    hints = get_type_hints(AgentModelPort.complete)
    #: return type is our own model, never a provider type
    assert hints["return"] is AgentModelResponse
    params = {p.name: p for p in sig.parameters.values() if p.name not in ("self", "cls")}
    assert set(params) == {"messages", "tools"}
    #: no provider SDK names in the annotation text
    for text in (str(hints), str(sig)):
        assert "openai" not in text.lower()
        assert "AsyncOpenAI" not in text
        assert "ChatCompletion" not in text


def test_response_can_carry_tool_call() -> None:
    resp = AgentModelResponse(
        content=None,
        tool_calls=[AgentToolCall(id="call_1", name="echo", raw_arguments='{"q":"x"}')],
        finish_reason="tool_calls",
    )
    assert resp.tool_calls[0].name == "echo"
    assert resp.tool_calls[0].id == "call_1"


def test_agent_message_roles() -> None:
    from dev_knowledge_agent.agent.models import AgentRole

    system = AgentMessage(role=AgentRole.SYSTEM, content="sys")
    tool = AgentMessage(role=AgentRole.TOOL, content="res", tool_call_id="call_1")
    assert system.role.value == "system"
    assert tool.tool_call_id == "call_1"


def test_tool_definition_is_not_an_openai_schema() -> None:
    """ToolDefinition is provider-neutral; conversion happens in the adapter."""
    td = ToolDefinition(name="echo", description="d", parameters=AgentMessage)
    assert td.parameters is AgentMessage
    assert not hasattr(td, "type")  #: no "function" marker until adapter converts
