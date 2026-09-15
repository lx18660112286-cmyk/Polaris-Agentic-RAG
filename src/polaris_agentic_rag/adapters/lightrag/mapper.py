"""LightRAG raw response -> Evidence Contract mapper.

The mapper is intentionally a pure, side-effect free function: it takes
a captured LightRAG ``aquery_data`` dict and a ``SourceResolver`` and
produces a domain ``KnowledgeSearchResult``. This keeps adapter.py free
of mapping code and makes the mapping offline-testable via fixtures.
"""

from __future__ import annotations

from typing import Any

from polaris_agentic_rag.adapters.lightrag.source_resolver import SourceResolver
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

__all__ = ["map_query_data_to_result"]


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_citation(
    reference_id: Any,
    file_path: Any,
    resolver: SourceResolver,
) -> Citation:
    """Build a Citation, resolving the basename via the SourceResolver."""
    source_name = _as_str(file_path)
    resolution = resolver.resolve(source_name)
    return Citation(
        reference_id=_as_str(reference_id) or "",
        source_name=source_name or "",
        source_path=(
            str(resolution.resolved_path)
            if resolution.status is SourceResolutionStatus.RESOLVED
            else None
        ),
        source_resolution=resolution.status,
    )


def _chunk_to_model(item: dict[str, Any]) -> ChunkEvidence:
    return ChunkEvidence(
        chunk_id=_as_str(item.get("chunk_id")) or "",
        content=_as_str(item.get("content")) or "",
        reference_id=_as_str(item.get("reference_id")),
        source_name=_as_str(item.get("file_path")),
    )


def _entity_to_model(item: dict[str, Any]) -> EntityEvidence:
    return EntityEvidence(
        entity_name=_as_str(item.get("entity_name")) or "",
        entity_type=_as_str(item.get("entity_type")),
        description=_as_str(item.get("description")),
        source_id=_as_str(item.get("source_id")),
        file_path=_as_str(item.get("file_path")),
        created_at=_as_str(item.get("created_at")),
        reference_id=_as_str(item.get("reference_id")),
        source_name=_as_str(item.get("file_path")),
    )


def _relationship_to_model(item: dict[str, Any]) -> RelationshipEvidence:
    return RelationshipEvidence(
        src_id=_as_str(item.get("src_id")) or "",
        tgt_id=_as_str(item.get("tgt_id")) or "",
        description=_as_str(item.get("description")),
        keywords=_as_str(item.get("keywords")),
        weight=_as_float(item.get("weight")),
        source_id=_as_str(item.get("source_id")),
        file_path=_as_str(item.get("file_path")),
        created_at=_as_str(item.get("created_at")),
        reference_id=_as_str(item.get("reference_id")),
    )


def _determine_availability(
    has_evidence: bool,
    processing_info: dict[str, Any],
) -> EvidenceAvailability:
    """Derive EvidenceAvailability from evidence presence + truncation info.

    We only claim TRUNCATED when the kernel explicitly reports truncation;
    we never claim SUFFICIENT because evidence presence does not guarantee
    it answers the query.
    """
    if not has_evidence:
        return EvidenceAvailability.NONE
    total_entities = _as_int(processing_info.get("total_entities_found"))
    after_entities = _as_int(processing_info.get("entities_after_truncation"))
    total_relations = _as_int(processing_info.get("total_relations_found"))
    after_relations = _as_int(processing_info.get("relations_after_truncation"))
    merged = _as_int(processing_info.get("merged_chunks_count"))
    final = _as_int(processing_info.get("final_chunks_count"))
    truncated = any(
        (
            total_entities is not None
            and after_entities is not None
            and after_entities < total_entities,
            total_relations is not None
            and after_relations is not None
            and after_relations < total_relations,
            merged is not None and final is not None and final < merged,
        )
    )
    return EvidenceAvailability.TRUNCATED if truncated else EvidenceAvailability.PRESENT


def map_query_data_to_result(
    data: dict[str, Any],
    query: str,
    resolver: SourceResolver,
) -> KnowledgeSearchResult:
    """Map a LightRAG ``aquery_data`` response dict to a KnowledgeSearchResult.

    ``data`` is expected to be the top-level ``aquery_data`` dict with
    ``status`` / ``message`` / ``data`` and optional ``metadata``.
    """
    data_block = data.get("data") or {}
    metadata = data.get("metadata") or {}

    chunks = [_chunk_to_model(c) for c in (data_block.get("chunks") or [])]
    entities = [_entity_to_model(e) for e in (data_block.get("entities") or [])]
    relationships = [_relationship_to_model(r) for r in (data_block.get("relationships") or [])]

    #: references drive citations; chunk/entity reference_ids also map back
    citations: list[Citation] = []
    seen_reference_ids: set[str] = set()
    for ref in data_block.get("references") or []:
        citation = _resolve_citation(ref.get("reference_id"), ref.get("file_path"), resolver)
        citations.append(citation)
        seen_reference_ids.add(citation.reference_id)

    #: attach resolved path to chunks/entities when a citation is unique
    citation_lookup = {c.reference_id: c for c in citations}
    resolved_chunks: list[ChunkEvidence] = []
    for chunk in chunks:
        if chunk.reference_id and chunk.reference_id in citation_lookup:
            cited = citation_lookup[chunk.reference_id]
            chunk = chunk.model_copy(
                update={
                    "source_name": cited.source_name,
                    "source_path": cited.source_path,
                }
            )
        resolved_chunks.append(chunk)

    resolved_entities: list[EntityEvidence] = []
    for entity in entities:
        if entity.reference_id and entity.reference_id in citation_lookup:
            cited = citation_lookup[entity.reference_id]
            entity = entity.model_copy(
                update={
                    "source_name": cited.source_name,
                    "source_path": cited.source_path,
                }
            )
        resolved_entities.append(entity)

    processing_info: dict[str, Any] = metadata.get("processing_info") or {}
    keywords_raw = metadata.get("keywords") or {}
    keywords = KeywordSet(
        high_level=[str(k) for k in (keywords_raw.get("high_level") or [])],
        low_level=[str(k) for k in (keywords_raw.get("low_level") or [])],
    )

    evidence = Evidence(
        chunks=resolved_chunks, entities=resolved_entities, relationships=relationships
    )
    diagnostics = RetrievalDiagnostics(
        keywords=keywords,
        entity_count=len(resolved_entities),
        relationship_count=len(relationships),
        chunk_count=len(resolved_chunks),
        reference_count=len(citations),
        total_entities_found=_as_int(processing_info.get("total_entities_found")),
        total_relations_found=_as_int(processing_info.get("total_relations_found")),
        entities_after_truncation=_as_int(processing_info.get("entities_after_truncation")),
        relations_after_truncation=_as_int(processing_info.get("relations_after_truncation")),
        merged_chunks_count=_as_int(processing_info.get("merged_chunks_count")),
        final_chunks_count=_as_int(processing_info.get("final_chunks_count")),
    )

    has_evidence = bool(
        diagnostics.chunk_count or diagnostics.entity_count or diagnostics.relationship_count
    )
    availability = _determine_availability(has_evidence, processing_info)

    return KnowledgeSearchResult(
        query=query,
        evidence=evidence,
        citations=citations,
        diagnostics=diagnostics,
        evidence_availability=availability,
    )
