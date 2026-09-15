"""Stage 1 LightRAG Native E2E integration tests.

These tests require real provider credentials (DeepSeek + local Ollama)
and are skipped by default in the offline suite. They never import
LightRAG directly; they go through the adapter harness
(``adapters/lightrag/native_baseline``), preserving the architecture
boundary.

Each test runs its whole lifecycle inside ONE ``asyncio.run``: LightRAG
binds its worker queues to the event loop that created them, so sharing
a constructed instance across event loops breaks.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from polaris_agentic_rag.adapters.lightrag.native_baseline import (
    build_lightrag,
    env_vars_available,
    ingest_documents,
    required_env_vars,
    run_query,
)

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KB_FILES = [
    PROJECT_ROOT / "examples" / "knowledge_base" / name
    for name in ("deployment.md", "api_auth.md", "incident_runbook.md", "service_overview.md")
]
FIXTURES = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "stage1_queries.json").read_text(encoding="utf-8")
)
CASES: dict[str, dict[str, Any]] = {c["case_id"]: c for c in FIXTURES["cases"]}
KB_BASENAMES = {p.name for p in KB_FILES}


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _skip_unless_credentials() -> None:
    if not env_vars_available():
        pytest.skip(f"Missing real provider credentials; required env vars: {required_env_vars()}")


def test_full_lifecycle_e2e(tmp_path: Path) -> None:
    """initialize -> ingest -> simple query -> aquery_data -> references -> finalize.

    Uses a temporary working directory so the developer baseline storage
    (``.local/lightrag_stage1``) is never polluted.
    """
    _skip_unless_credentials()
    workdir = tmp_path / "lightrag_stage1"

    async def scenario() -> dict[str, Any]:
        rag = build_lightrag(workdir)
        try:
            await rag.initialize_storages()
            await ingest_documents(rag, KB_FILES)
            assert workdir.is_dir() and any(workdir.iterdir())

            #: simple factual query (Case A)
            simple = await run_query(rag, CASES["A_simple_fact"]["query"], mode="hybrid")
            assert simple.error is None, simple.error
            assert simple.answered, "no answer text returned"
            assert simple.data_status == "success"
            assert simple.references, "references are empty for a factual query"
            for ref in simple.references:
                path = str(ref.get("file_path", ""))
                assert Path(path).name in KB_BASENAMES, f"reference outside KB: {path}"

            #: aquery_data structure
            assert simple.entities >= 0 and simple.relationships >= 0
            assert simple.chunks > 0, "hybrid mode returned no chunks"

            #: multi-document query (Case D)
            multi = await run_query(rag, CASES["D_multi_document_5xx"]["query"], mode="hybrid")
            assert multi.error is None, multi.error
            assert multi.answered
            assert len(multi.source_files) >= 2, (
                f"multi-document query returned {len(multi.source_files)} source file(s)"
            )

            #: unknown question recorded without crash (Case G)
            unknown = await run_query(rag, CASES["G_unanswerable"]["query"], mode="hybrid")
            assert unknown.error is None, unknown.error

            return {
                "simple_answered": simple.answered,
                "simple_references": [dict(r) for r in simple.references],
                "multi_sources": multi.source_files,
                "unknown_answered": unknown.answered,
            }
        finally:
            await rag.finalize_storages()

    summary = _run(scenario())
    assert summary["simple_answered"]
    assert summary["unknown_answered"]


def test_failure_shapes_without_side_effects() -> None:
    """Cost-free failure probes: empty query and query before init."""
    _skip_unless_credentials()

    async def probe() -> dict[str, Any]:
        rag = build_lightrag(PROJECT_ROOT / ".local" / "never_initialized_tmp")

        #: empty query -> validation failure captured as an error observation
        empty_obs = await run_query(rag, "", mode="hybrid")
        empty_error = empty_obs.error or "no error"

        #: query before initialize_storages -> storage lifecycle failure captured
        not_init_obs = await run_query(rag, "Access token 的有效期是多少？", mode="hybrid")
        not_init_error = not_init_obs.error or "no error"
        await rag.finalize_storages()
        return {"empty_error": empty_error, "not_init_error": not_init_error}

    result = _run(probe())
    #: pinned kernel raises EmptyQueryError for empty queries (observed)
    assert "empty" in result["empty_error"].lower(), result["empty_error"]
    #: pinned kernel raises a TypeError on uninitialized storages (observed)
    not_init_lower = result["not_init_error"].lower()
    assert "NoneType" in result["not_init_error"] or "not initialized" in not_init_lower, result[
        "not_init_error"
    ]
