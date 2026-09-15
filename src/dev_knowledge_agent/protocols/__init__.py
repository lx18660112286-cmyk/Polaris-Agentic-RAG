"""Protocols (interfaces) for the Dev Knowledge Agent core.

``KnowledgeSearchPort`` is the framework-agnostic retrieval abstraction:
the Tool depends on it, the Adapter implements it, and the two never
couple directly.
"""

from __future__ import annotations

from dev_knowledge_agent.protocols.knowledge_search import KnowledgeSearchPort

__all__ = ["KnowledgeSearchPort"]
