"""Evidence Contract (domain models).

Stage 2's Evidence Contract is OUR domain model -- not a LightRAG raw
dict. It is framework-agnostic and carries no LightRAG types.

Field shapes are grounded in the pinned LightRAG kernel's real
``aquery_data`` output observed in Stage 1:

* chunk      : content, file_path, chunk_id, reference_id
* entity     : entity_name, entity_type, description, source_id,
               file_path, created_at, reference_id
* relationship: src_id, tgt_id, description, keywords, weight,
               source_id, file_path, created_at, reference_id
* reference  : reference_id, file_path
* metadata.keywords.{high_level, low_level}
* metadata.processing_info.{total_entities_found,
               total_relations_found, entities_after_truncation,
               relations_after_truncation, merged_chunks_count,
               final_chunks_count}

If a raw field is absent from the payload we keep it ``None`` rather
than fabricating a value.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "SourceResolutionStatus",
    "EvidenceAvailability",
    "Citation",
    "ChunkEvidence",
    "EntityEvidence",
    "RelationshipEvidence",
    "RetrievalDiagnostics",
    "KeywordSet",
    "Evidence",
    "KnowledgeSearchResult",
]


class SourceResolutionStatus(str, Enum):
    """Outcome of resolving a citation basename to a project source path."""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"


class EvidenceAvailability(str, Enum):
    """How much retrieval evidence is available for a search."""

    NONE = "NONE"
    PRESENT = "PRESENT"
    TRUNCATED = "TRUNCATED"


class Citation(BaseModel):
    """One source citation referenced by the retrieval result.

    ``source_name`` is always kept (e.g. ``api_auth.md``) even when the
    path cannot be resolved. ``source_path`` is ``None`` unless the
    resolution is unambiguous.
    """

    reference_id: str
    source_name: str
    source_path: str | None = None
    source_resolution: SourceResolutionStatus = SourceResolutionStatus.UNRESOLVED


class ChunkEvidence(BaseModel):
    """A document chunk that supports the answer."""

    chunk_id: str
    content: str
    reference_id: str | None = None
    source_name: str | None = None
    source_path: str | None = None


class EntityEvidence(BaseModel):
    """A knowledge-graph entity retrieved for the query.

    Only real fields from the pinned kernel payload are mapped.
    ``source_name`` / ``source_path`` are resolved citation metadata.
    """

    entity_name: str
    entity_type: str | None = None
    description: str | None = None
    source_id: str | None = None
    file_path: str | None = None
    created_at: str | None = None
    reference_id: str | None = None
    source_name: str | None = None
    source_path: str | None = None


class RelationshipEvidence(BaseModel):
    """A knowledge-graph relationship retrieved for the query.

    In ``naive`` mode the kernel returns no entities/relationships; an
    empty list is a legal result, so nothing here is required.
    """

    src_id: str
    tgt_id: str
    description: str | None = None
    keywords: str | None = None
    weight: float | None = None
    source_id: str | None = None
    file_path: str | None = None
    created_at: str | None = None
    reference_id: str | None = None


class KeywordSet(BaseModel):
    """Keywords extracted by the kernel for the query."""

    high_level: list[str] = Field(default_factory=list)
    low_level: list[str] = Field(default_factory=list)


class RetrievalDiagnostics(BaseModel):
    """Normalized retrieval diagnostics from the kernel.

    Only fields actually observed in the real payload are mapped; the
    kernel may omit ``processing_info`` entirely, hence all ``None``.
    """

    keywords: KeywordSet = Field(default_factory=KeywordSet)
    entity_count: int = 0
    relationship_count: int = 0
    chunk_count: int = 0
    reference_count: int = 0

    #: From metadata.processing_info (optional)
    total_entities_found: int | None = None
    total_relations_found: int | None = None
    entities_after_truncation: int | None = None
    relations_after_truncation: int | None = None
    merged_chunks_count: int | None = None
    final_chunks_count: int | None = None


class Evidence(BaseModel):
    """Structured evidence returned by a knowledge search."""

    chunks: list[ChunkEvidence] = Field(default_factory=list)
    entities: list[EntityEvidence] = Field(default_factory=list)
    relationships: list[RelationshipEvidence] = Field(default_factory=list)


class KnowledgeSearchResult(BaseModel):
    """Domain result of a knowledge search (framework-agnostic).

    This is the Port-level result. It deliberately does NOT include a
    ``QueryParam`` or any LightRAG object.
    """

    query: str
    evidence: Evidence = Field(default_factory=Evidence)
    citations: list[Citation] = Field(default_factory=list)
    diagnostics: RetrievalDiagnostics = Field(default_factory=RetrievalDiagnostics)
    evidence_availability: EvidenceAvailability = EvidenceAvailability.NONE

    model_config = ConfigDict(extra="forbid")
