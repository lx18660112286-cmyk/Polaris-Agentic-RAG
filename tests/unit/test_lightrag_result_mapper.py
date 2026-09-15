"""Contract tests: LightRAG raw payload -> Evidence Contract via Mapper.

These run offline against sanitized fixtures captured from Stage 1's real
``aquery_data`` output, so the vendor contract mapping is guarded even in
the default (non-integration) suite.
"""

from __future__ import annotations

import json
from pathlib import Path

from dev_knowledge_agent.adapters.lightrag.mapper import map_query_data_to_result
from dev_knowledge_agent.adapters.lightrag.source_resolver import SourceResolver
from dev_knowledge_agent.evidence.models import (
    EvidenceAvailability,
    SourceResolutionStatus,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lightrag"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _make_root(tmp_path: Path, *basenames: str) -> Path:
    root = tmp_path / "kb"
    root.mkdir(parents=True, exist_ok=True)
    for name in basenames:
        (root / name).write_text("doc", encoding="utf-8")
    return root


def test_hybrid_success_maps_chunks_references_and_diagnostics(tmp_path: Path) -> None:
    root = _make_root(tmp_path, "api_auth.md", "deployment.md")
    resolver = SourceResolver([root])
    payload = _load("hybrid_success.json")

    result = map_query_data_to_result(payload, "Access token 的有效期是多少？", resolver)

    #: entities / relationships present
    assert len(result.evidence.entities) == 2
    assert len(result.evidence.relationships) == 1
    #: chunk mapped with content and resolved source path
    assert len(result.evidence.chunks) == 1
    chunk = result.evidence.chunks[0]
    assert chunk.reference_id == "1"
    assert chunk.source_name == "api_auth.md"
    assert chunk.source_path == str((root / "api_auth.md").resolve())

    #: citation resolution
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.reference_id == chunk.reference_id
    assert citation.source_name == "api_auth.md"
    assert citation.source_resolution is SourceResolutionStatus.RESOLVED

    #: diagnostics
    assert result.diagnostics.entity_count == 2
    assert result.diagnostics.chunk_count == 1
    assert result.diagnostics.total_entities_found == 30
    assert result.diagnostics.entities_after_truncation == 2
    #: presence with truncation reported
    assert result.evidence_availability is EvidenceAvailability.TRUNCATED
    #: no forbidden fields
    assert not hasattr(result, "mode")
    assert not hasattr(result, "top_k")


def test_naive_success_supports_empty_entities_and_relationships(tmp_path: Path) -> None:
    root = _make_root(tmp_path, "deployment.md")
    resolver = SourceResolver([root])
    payload = _load("naive_success.json")

    result = map_query_data_to_result(payload, "deployment", resolver)

    assert result.evidence.entities == []
    assert result.evidence.relationships == []
    assert len(result.evidence.chunks) == 1
    assert result.evidence_availability is EvidenceAvailability.PRESENT


def test_failure_payload_maps_to_empty_none_availability(tmp_path: Path) -> None:
    """Mapper is a pure function: it maps whatever shape it is given.

    The adapter is responsible for surfacing a non-success status as an
    error; the mapper still deterministically produces a domain result.
    """
    root = _make_root(tmp_path, "deployment.md")
    resolver = SourceResolver([root])
    payload = _load("failure.json")

    result = map_query_data_to_result(payload, "unrelated", resolver)
    assert result.evidence.chunks == []
    assert result.evidence_availability is EvidenceAvailability.NONE
    assert result.diagnostics.reference_count == 0


def test_ambiguous_basename_yields_ambiguous_citation(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    (root / "a").mkdir(parents=True, exist_ok=True)
    (root / "b").mkdir(parents=True, exist_ok=True)
    (root / "a" / "deployment.md").write_text("x", encoding="utf-8")
    (root / "b" / "deployment.md").write_text("y", encoding="utf-8")
    resolver = SourceResolver([root])
    payload = _load("naive_success.json")

    result = map_query_data_to_result(payload, "x", resolver)
    assert len(result.citations) == 1
    assert result.citations[0].source_resolution is SourceResolutionStatus.AMBIGUOUS
    assert result.citations[0].source_path is None


def test_chunk_reference_id_maps_to_citation_reference_id(tmp_path: Path) -> None:
    root = _make_root(tmp_path, "deployment.md")
    resolver = SourceResolver([root])
    payload = _load("hybrid_success.json")

    result = map_query_data_to_result(payload, "token", resolver)
    citation_ids = {c.reference_id for c in result.citations}
    #: at least one chunk/entity reference_id must appear among citations
    for chunk in result.evidence.chunks:
        if chunk.reference_id:
            assert chunk.reference_id in citation_ids
