"""Tool protocol and schema (framework-agnostic AgentTool).

Stage 4 introduces a minimal ``AgentTool`` abstraction so the
``RagSearchTool`` (Stage 2/3) can be surfaced to the Agent loop without
being rewritten and without coupling to LangChain / LangGraph / an
OpenAI SDK tool class.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

__all__ = ["AgentTool", "ToolDefinition", "ToolExecutionResult"]


class ToolDefinition(BaseModel):
    """Provider-neutral description of a tool registered in the registry.

    ``parameters`` is a Pydantic model: its JSON schema (via
    ``model_json_schema``) is converted by the *provider adapter* into the
    provider's function schema, so we never maintain a second schema by hand.
    """

    name: str
    description: str
    parameters: type[BaseModel]


class ToolExecutionResult(BaseModel):
    """Outcome of running one tool in the registry (before formatting).

    Defined here (not in ``agent/``) so ``tools/registry`` never depends on
    the agent package, avoiding an import cycle with the orchestrator.
    """

    name: str
    ok: bool
    value: Any = None
    error: str | None = None


@runtime_checkable
class AgentTool(Protocol):
    """Structural contract every relocatable tool must satisfy."""

    name: str
    description: str

    @property
    def input_schema(self) -> type[BaseModel]: ...

    async def invoke(self, input_: BaseModel) -> Any: ...
