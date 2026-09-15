"""Protocols (interfaces) for the Dev Knowledge Agent core.

Framework-agnostic abstractions:
- ``KnowledgeSearchPort`` -- retrieval abstraction (Tool depends on it, the
  Adapter implements it).
- ``AgentModelPort`` -- Agent-LLM abstraction (Orchestrator depends on it,
  the Agent Model Adapter implements it).
"""

from __future__ import annotations

from polaris_agentic_rag.protocols.agent_model import AgentModelPort
from polaris_agentic_rag.protocols.knowledge_search import KnowledgeSearchPort

__all__ = ["AgentModelPort", "KnowledgeSearchPort"]
