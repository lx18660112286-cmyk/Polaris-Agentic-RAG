"""Tool-layer domain exceptions (framework/provider-neutral).

These are the application's own errors. They never import provider SDKs or
LightRAG. The orchestrator maps them into graceful tool messages so a
malformed/unknown tool call never leaks a Python traceback to the user.
"""

from __future__ import annotations

__all__ = [
    "ToolError",
    "DuplicateToolError",
    "UnknownToolError",
    "InvalidToolArgumentsError",
]


class ToolError(Exception):
    """Base error for tool registry / invocation failures."""


class DuplicateToolError(ToolError):
    """A tool with the same name was registered twice."""


class UnknownToolError(ToolError):
    """The requested tool name was never registered."""


class InvalidToolArgumentsError(ToolError):
    """Tool arguments failed to parse or validate against the input schema."""
