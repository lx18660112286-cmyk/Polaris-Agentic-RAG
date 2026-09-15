"""Stage 2 RagSearchTool real E2E integration test.

Proves the real path:
    RagSearchTool -> KnowledgeSearchPort -> LightRAGAdapter -> LightRAG

Uses the same pinned providers (DeepSeek + Ollama bge-m3) and the same
lifecycle policy as Stage 1. One real kernel: ingest via the harness,
then bind the SAME kernel to the adapter and search through the Tool.
Requires provider credentials, so this test is skipped by default unless
``DEEPSEEK_API_KEY`` is present.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from dev_knowledge_agent.adapters.lightrag.adapter import LightRAGAdapter
from dev_knowledge_agent.adapters.lightrag.native_baseline import (
    env_vars_available,
    ingest_documents,
)
from dev_knowledge_agent.tools.rag_search import RagSearchInput, RagSearchStatus, RagSearchTool

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KB_FILES = [
    PROJECT_ROOT / "examples" / "knowledge_base" / name
    for name in ("deployment.md", "api_auth.md", "incident_runbook.md", "service_overview.md")
]
FIXTURES = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "stage1_queries.json").read_text(encoding="utf-8")
)
SIMPLE_QUERY = "Access token 的有效期是多少？"


def _skip_unless_credentials() -> None:
    if not env_vars_available():
        pytest.skip("Real provider credentials are required (DEEPSEEK_API_KEY)")


def test_rag_search_tool_real_e2e(tmp_path: Path) -> None:
    """initialize -> ingest -> tool.invoke -> verify domain result -> close."""
    _skip_unless_credentials()
    workdir = tmp_path / "lightrag_stage2"

    async def scenario() -> dict:
        #: one real kernel: the adapter owns lifecycle + kernel construction.
        #: This exactly mirrors production startup policy:
        #:   1. Application startup → adapter.initialize (builds + inits kernel)
        #:   2. Ingestion once at startup (through the same kernel)
        #:   3. Tool invokes search for each user query
        #:   4. Application shutdown → adapter.close (finalize_storages)
        #:
        #: Workspace isolation: LightRAG scopes dedup and storage by the ``workspace``
        #: argument. We pass a unique token derived from tmp_path to avoid cross-test
        #: duplicate detection when running both Stage 1 and Stage 2 integration
        #: tests in the same pytest session.
        from dev_knowledge_agent.adapters.lightrag.settings import LightRAGAdapterSettings

        settings = LightRAGAdapterSettings(
            working_dir=workdir,
            workspace=f"dka_stage2_{workdir.resolve().name}",
        )
        adapter = LightRAGAdapter(
            working_dir=workdir,
            settings=settings,
            knowledge_roots=[PROJECT_ROOT / "examples"],
        )
        tool = RagSearchTool(search_port=adapter)  # type: ignore[type-abstract]
        try:
            await adapter.initialize()
            #: retrieve the kernel built by initialize() to run ingestion once.
            kernel = adapter._kernel  # noqa: SLF001 - test probes the kernel
            assert kernel is not None
            await ingest_documents(kernel, KB_FILES)
            result = await tool.invoke(RagSearchInput(query=SIMPLE_QUERY))
            assert result.status is RagSearchStatus.SUCCESS, result.error
            assert result.evidence.chunks, "no chunks returned"
            assert result.citations, "no citations returned"
            assert any(c.source_name == "api_auth.md" for c in result.citations), (
                "expected a citation to api_auth.md"
            )
            assert any(c.source_resolution.value == "RESOLVED" for c in result.citations), (
                "expected a resolved citation"
            )
            return {
                "status": result.status.value,
                "chunks": len(result.evidence.chunks),
                "citations": [c.model_dump() for c in result.citations],
                "diagnostics": result.diagnostics.model_dump(),
            }
        finally:
            await adapter.close()

    summary = asyncio.run(scenario())
    assert summary["status"] == "SUCCESS"
