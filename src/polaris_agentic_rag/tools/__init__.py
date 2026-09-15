"""Agent-facing tools.

``RagSearchTool`` is the knowledge retrieval tool (Stage 2/3); Stage 4
adds the generic ``AgentTool`` contract and a provider-neutral
``ToolRegistry``. External tools (Git/Log/Database/Web) come in Stage 6.
"""

from __future__ import annotations

from polaris_agentic_rag.tools.errors import (
    DuplicateToolError,
    InvalidToolArgumentsError,
    ToolError,
    UnknownToolError,
)
from polaris_agentic_rag.tools.protocol import AgentTool, ToolDefinition
from polaris_agentic_rag.tools.rag_search import (
    TOOL_DESCRIPTION,
    TOOL_NAME,
    RagSearchInput,
    RagSearchResult,
    RagSearchStatus,
    RagSearchTool,
)
from polaris_agentic_rag.tools.registry import ToolRegistry

__all__ = [
    "AgentTool",
    "DuplicateToolError",
    "InvalidToolArgumentsError",
    "RagSearchInput",
    "RagSearchResult",
    "RagSearchStatus",
    "RagSearchTool",
    "TOOL_DESCRIPTION",
    "TOOL_NAME",
    "ToolDefinition",
    "ToolError",
    "ToolRegistry",
    "UnknownToolError",
]
