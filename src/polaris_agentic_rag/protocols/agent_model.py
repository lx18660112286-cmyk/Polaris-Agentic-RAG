"""AgentModelPort -- provider-neutral interface for the Agent LLM.

The AgentOrchestrator depends on this Protocol, never on a provider SDK
(OpenAI / AsyncOpenAI / DeepSeek SDK). Provider adapters (e.g.
``adapters/agent_model/deepseek.py``) implement it by translating these
domain types to/from the provider's wire types.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from polaris_agentic_rag.agent.models import AgentMessage, AgentModelResponse
from polaris_agentic_rag.tools.protocol import ToolDefinition

__all__ = ["AgentModelPort"]


@runtime_checkable
class AgentModelPort(Protocol):
    """Abstract Agent-LLM capability for the orchestrator layer."""

    async def complete(
        self,
        messages: list[AgentMessage],
        tools: list[ToolDefinition],
    ) -> AgentModelResponse:
        """Run one completion and return the provider-neutral response.

        The model may return assistant text and/or ``tool_calls``. Raises
        provider-agnostic errors (never leaked vendor exceptions).
        """
        ...
