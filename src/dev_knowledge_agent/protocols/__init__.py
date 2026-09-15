"""Protocols (interfaces) for the Dev Knowledge Agent core.

Framework-agnostic abstractions:
- ``KnowledgeSearchPort`` -- retrieval abstraction (Tool depends on it, the
  Adapter implements it).
- ``AgentModelPort`` -- Agent-LLM abstraction (Orchestrator depends on it,
  the Agent Model Adapter implements it).
"""

from __future__ import annotations

from dev_knowledge_agent.protocols.agent_model import AgentModelPort
from dev_knowledge_agent.protocols.knowledge_search import KnowledgeSearchPort

__all__ = ["AgentModelPort", "KnowledgeSearchPort"]
