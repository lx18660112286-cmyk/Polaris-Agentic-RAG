"""Agent-layer domain exceptions.

Distinguish terminal conditions the orchestrator surfaces in an
``AgentResult`` (via ``AgentStatus``) from unrecoverable model failures.
Never import provider SDKs or LightRAG.
"""

from __future__ import annotations

__all__ = [
    "AgentError",
    "AgentMaxStepsExceededError",
    "AgentMaxToolCallsExceededError",
    "AgentDuplicateCallError",
]


class AgentError(Exception):
    """Base error for the Agent orchestration layer."""


class AgentMaxStepsExceededError(AgentError):
    """The Agent loop hit the configured ``max_steps`` cap."""


class AgentMaxToolCallsExceededError(AgentError):
    """The Agent loop hit the configured ``max_tool_calls`` cap."""


class AgentDuplicateCallError(AgentError):
    """The model repeated an identical tool call (name + arguments)."""
