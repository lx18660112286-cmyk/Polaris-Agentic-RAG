"""ToolRegistry -- registers and invokes AgentTools for the Agent loop.

The registry only manages the application ``AgentTool`` abstraction. It
does NOT depend on a model provider (DeepSeek/OpenAI) and does NOT know
about LightRAG. Provider adapters turn ``ToolDefinition`` into a provider
function schema; the registry is provider-agnostic.
"""

from __future__ import annotations

import json
from typing import Any

from polaris_agentic_rag.tools.errors import (
    DuplicateToolError,
    InvalidToolArgumentsError,
    UnknownToolError,
)
from polaris_agentic_rag.tools.protocol import AgentTool, ToolDefinition, ToolExecutionResult

__all__ = ["ToolRegistry"]


class ToolRegistry:
    """A provider-neutral registry of application tools."""

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    def register(self, tool: AgentTool) -> None:
        """Register a tool. Duplicate registration -> DuplicateToolError."""
        name = tool.name
        if name in self._tools:
            raise DuplicateToolError(f"Tool {name!r} is already registered")
        self._tools[name] = tool

    def get(self, name: str) -> AgentTool:
        """Look up a tool by name. Unknown -> UnknownToolError."""
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownToolError(f"Unknown tool {name!r}")
        return tool

    def definitions(self) -> list[ToolDefinition]:
        """Return provider-neutral definitions for all registered tools."""
        return [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters=tool.input_schema,
            )
            for tool in self._tools.values()
        ]

    @staticmethod
    def _parse_arguments(raw_arguments: str) -> dict[str, Any]:
        """Parse + basic-validate the raw tool arguments JSON string."""
        if not raw_arguments or not raw_arguments.strip():
            raise InvalidToolArgumentsError("Tool arguments are missing/empty")
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise InvalidToolArgumentsError(f"Malformed JSON in tool arguments: {exc}") from exc
        if not isinstance(parsed, dict):
            raise InvalidToolArgumentsError("Tool arguments must be a JSON object")
        return parsed

    async def invoke(
        self,
        name: str,
        raw_arguments: str,
    ) -> ToolExecutionResult:
        """Validate and execute a tool call.

        Order per spec §19: JSON parse -> input-schema validation -> invoke.
        Any of these failing raises a ToolError subclass; never a raw
        traceback to the caller.
        """
        tool = self.get(name)
        parsed = self._parse_arguments(raw_arguments)
        try:
            validated = tool.input_schema(**parsed)
        except Exception as exc:  # noqa: BLE001 - pydantic ValidationError etc.
            raise InvalidToolArgumentsError(
                f"Tool {name!r} arguments failed validation: {exc}"
            ) from exc
        value = await tool.invoke(validated)
        return ToolExecutionResult(name=name, ok=True, value=value)
