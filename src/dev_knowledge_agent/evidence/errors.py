"""Domain exceptions for the knowledge search layer.

These are our own exceptions -- they never import or expose LightRAG.
The adapter maps LightRAG-specific failures onto these so they never
leak to the Tool / Agent.
"""

from __future__ import annotations

__all__ = [
    "KnowledgeSearchError",
    "KnowledgeSearchNotReadyError",
    "KnowledgeSearchExecutionError",
    "InvalidKnowledgeQueryError",
]


class KnowledgeSearchError(Exception):
    """Base error for knowledge search failures."""


class KnowledgeSearchNotReadyError(KnowledgeSearchError):
    """Search was invoked before the storage/query lifecycle was ready."""


class KnowledgeSearchExecutionError(KnowledgeSearchError):
    """The search execution failed inside the underlying kernel."""


class InvalidKnowledgeQueryError(KnowledgeSearchError):
    """The query is invalid (e.g. empty / whitespace)."""
