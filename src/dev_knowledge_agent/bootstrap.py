"""Composition root (Stage 2 -> Stage 4).

The composition root is the only place allowed to know concrete
implementations. It wires:

    Settings
     -> LightRAGAdapter (KnowledgeSearchPort)
     -> QueryRouter
     -> RagSearchTool (AgentTool)
     -> ToolRegistry
     -> DeepSeekAgentModelAdapter (AgentModelPort)
     -> AgentOrchestrator

The orchestrator / tools / registry themselves never import the concrete
adapter or the provider SDK.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dev_knowledge_agent.adapters.agent_model.deepseek import DeepSeekAgentModelAdapter
from dev_knowledge_agent.adapters.lightrag.adapter import LightRAGAdapter
from dev_knowledge_agent.adapters.lightrag.settings import (
    LightRAGAdapterSettings,
    get_lightrag_adapter_settings,
)
from dev_knowledge_agent.agent.orchestrator import AgentOrchestrator
from dev_knowledge_agent.agent.prompts import build_system_prompt
from dev_knowledge_agent.config.settings import Settings, get_settings
from dev_knowledge_agent.retrieval.router import QueryRouter
from dev_knowledge_agent.tools.rag_search import AgentRagSearchTool, RagSearchTool
from dev_knowledge_agent.tools.registry import ToolRegistry

__all__ = [
    "BuiltAgent",
    "build_rag_search_tool",
    "create_lightrag_adapter",
    "build_agent",
    "build_agent_orchestrator",
]


@dataclass(frozen=True)
class BuiltAgent:
    """The composed agent application for a caller to run & lifecycle-manage."""

    rag_tool: RagSearchTool
    registry: ToolRegistry
    orchestrator: AgentOrchestrator
    adapter: LightRAGAdapter


def create_lightrag_adapter(
    settings: LightRAGAdapterSettings | None = None,
    working_dir: str | Path | None = None,
    knowledge_roots: list[Path] | None = None,
) -> LightRAGAdapter:
    """Build a LightRAGAdapter from settings (only used by the composition root)."""
    return LightRAGAdapter(
        working_dir=working_dir,
        settings=settings or get_lightrag_adapter_settings(),
        knowledge_roots=knowledge_roots,
    )


def build_rag_search_tool(*, adapter: LightRAGAdapter) -> RagSearchTool:
    """Bind the concrete adapter to a RagSearchTool via the Port + Router."""
    return RagSearchTool(search_port=adapter, router=QueryRouter())


def build_agent_orchestrator(
    *,
    model_adapter: DeepSeekAgentModelAdapter,
    registry: ToolRegistry,
    system_prompt: str,
    max_steps: int,
    max_tool_calls: int,
) -> AgentOrchestrator:
    """Assemble the orchestrator from its collaborators."""
    return AgentOrchestrator(
        model=model_adapter,
        registry=registry,
        system_prompt=system_prompt,
        max_steps=max_steps,
        max_tool_calls=max_tool_calls,
    )


def build_agent(
    settings: Settings | None = None,
    *,
    lightrag_adapter: LightRAGAdapter | None = None,
    working_dir: str | Path | None = None,
) -> BuiltAgent:
    """Compose RagSearchTool + ToolRegistry + AgentOrchestrator (Stage 4).

    Returns a ``BuiltAgent`` so a caller (CLI / integration test) can run the
    orchestrator and manage the LightRAG adapter lifecycle
    (``built.adapter.initialize()`` / ``close()``) itself.
    """
    settings = settings or get_settings()

    adapter = lightrag_adapter or create_lightrag_adapter(
        working_dir=working_dir,
        knowledge_roots=None,
    )

    rag_tool = build_rag_search_tool(adapter=adapter)
    #: RagSearchTool is surfaced to the registry through an AgentTool-compatible
    #: thin wrapper (spec §15) so the Tool's own contract stays untouched.
    agent_tool = AgentRagSearchTool(rag_tool)

    registry = ToolRegistry()
    registry.register(agent_tool)

    #: Agent LLM wiring is independent of the LightRAG kernel LLM.
    model_adapter = DeepSeekAgentModelAdapter(
        model=settings.agent_model,
        base_url=settings.agent_base_url,
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        temperature=settings.agent_temperature,
    )

    system_prompt = build_system_prompt(agent_tool)
    orchestrator = build_agent_orchestrator(
        model_adapter=model_adapter,
        registry=registry,
        system_prompt=system_prompt,
        max_steps=settings.agent_max_steps,
        max_tool_calls=settings.agent_max_tool_calls,
    )

    return BuiltAgent(
        rag_tool=rag_tool,
        registry=registry,
        orchestrator=orchestrator,
        adapter=adapter,
    )
