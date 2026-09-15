"""Evidence / Search Result contracts.

The Evidence Contract (``models``) is OUR domain model and is
framework-agnostic. It carries no LightRAG types. Domain exceptions
(``errors``) also never import LightRAG.
"""

from __future__ import annotations

from polaris_agentic_rag.evidence.models import (
    ChunkEvidence,
    Citation,
    EntityEvidence,
    Evidence,
    EvidenceAvailability,
    KeywordSet,
    KnowledgeSearchResult,
    RelationshipEvidence,
    RetrievalDiagnostics,
    SourceResolutionStatus,
)

__all__ = [
    "ChunkEvidence",
    "Citation",
    "EntityEvidence",
    "Evidence",
    "EvidenceAvailability",
    "KeywordSet",
    "KnowledgeSearchResult",
    "RelationshipEvidence",
    "RetrievalDiagnostics",
    "SourceResolutionStatus",
]
