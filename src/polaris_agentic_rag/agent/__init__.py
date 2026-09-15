"""Agent orchestration layer (Stage 4).

Implements the single-agent tool-calling loop: ``AgentOrchestrator``
(native tool calling) over ``AgentModelPort`` and a ``ToolRegistry``. This
layer is provider-neutral -- it never imports provider SDKs (openai) or
LightRAG.

``AgentOrchestrator`` is intentionally NOT re-exported from this package
top-level: importing it here would eagerly pull in ``protocols.agent_model``
and create an import cycle with ``agent.models``. Import it explicitly from
``polaris_agentic_rag.agent.orchestrator`` instead.
"""

from __future__ import annotations

from polaris_agentic_rag.agent.errors import (
    AgentDuplicateCallError,
    AgentError,
    AgentMaxStepsExceededError,
    AgentMaxToolCallsExceededError,
)
from polaris_agentic_rag.agent.models import (
    AgentMessage,
    AgentModelResponse,
    AgentResult,
    AgentRole,
    AgentStatus,
    AgentToolCall,
    TokenUsage,
    ToolCallRecord,
)
from polaris_agentic_rag.agent.prompts import build_system_prompt
from polaris_agentic_rag.tools.protocol import ToolExecutionResult

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
    "TokenUsage",
    "ToolCallRecord",
    "ToolExecutionResult",
    "build_system_prompt",
]
