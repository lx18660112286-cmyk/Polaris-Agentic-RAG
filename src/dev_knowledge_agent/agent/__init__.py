"""Agent orchestration layer (Stage 4).

Implements the single-agent tool-calling loop: ``AgentOrchestrator``
(native tool calling) over ``AgentModelPort`` and a ``ToolRegistry``. This
layer is provider-neutral -- it never imports provider SDKs (openai) or
LightRAG.

``AgentOrchestrator`` is intentionally NOT re-exported from this package
top-level: importing it here would eagerly pull in ``protocols.agent_model``
and create an import cycle with ``agent.models``. Import it explicitly from
``dev_knowledge_agent.agent.orchestrator`` instead.
"""

from __future__ import annotations

from dev_knowledge_agent.agent.errors import (
    AgentDuplicateCallError,
    AgentError,
    AgentMaxStepsExceededError,
    AgentMaxToolCallsExceededError,
)
from dev_knowledge_agent.agent.models import (
    AgentMessage,
    AgentModelResponse,
    AgentResult,
    AgentRole,
    AgentStatus,
    AgentToolCall,
    ToolCallRecord,
)
from dev_knowledge_agent.agent.prompts import build_system_prompt
from dev_knowledge_agent.tools.protocol import ToolExecutionResult

__all__ = [
    "AgentDuplicateCallError",
    "AgentError",
    "AgentMaxStepsExceededError",
    "AgentMaxToolCallsExceededError",
    "AgentMessage",
    "AgentModelResponse",
    "AgentResult",
    "AgentRole",
    "AgentStatus",
    "AgentToolCall",
    "ToolCallRecord",
    "ToolExecutionResult",
    "build_system_prompt",
]
