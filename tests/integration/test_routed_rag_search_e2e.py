"""Stage 3 routed RagSearchTool real E2E integration test.

Consolidates the Stage 3 acceptance paths (spec §24):
    query -> RagSearchTool -> QueryRouter -> RetrievalPlan
              -> KnowledgeSearchPort -> LightRAGAdapter -> LightRAG

Runs factual + multi-document queries through ONE kernel (single ingest),
verifying: routing decision, evidence, citations, and that the real query
succeeds. Requires provider credentials (skipped by default without
``DEEPSEEK_API_KEY``).
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
from dev_knowledge_agent.retrieval.models import RetrievalIntent
from dev_knowledge_agent.retrieval.router import QueryRouter
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
FACTUAL_QUERY = "Access token 的有效期是多少？"  # -> FOCUSED
MULTI_DOC_QUERY = "Order Service 发布后出现大量 5xx，应如何定位问题并判断是否回滚？"  # -> HYBRID


def _skip_unless_credentials() -> None:
    if not env_vars_available():
        pytest.skip("Real provider credentials are required (DEEPSEEK_API_KEY)")


def test_routed_rag_search_real_e2e(tmp_path: Path) -> None:
    """initialize -> ingest -> route(factual) -> route(multi-doc) -> close."""
    _skip_unless_credentials()
    workdir = tmp_path / "lightrag_stage3"

    async def scenario() -> dict:
        from dev_knowledge_agent.adapters.lightrag.settings import LightRAGAdapterSettings

        settings = LightRAGAdapterSettings(
            working_dir=workdir,
            workspace=f"dka_stage3_{workdir.resolve().name}",
        )
        adapter = LightRAGAdapter(
            working_dir=workdir,
            settings=settings,
            knowledge_roots=[PROJECT_ROOT / "examples"],
        )
        router = QueryRouter()
        tool = RagSearchTool(search_port=adapter, router=router)  # type: ignore[type-abstract]
        try:
            await adapter.initialize()
            kernel = adapter._kernel  # noqa: SLF001 - test probes the kernel
            assert kernel is not None
            await ingest_documents(kernel, KB_FILES)

            factual = await tool.invoke(RagSearchInput(query=FACTUAL_QUERY))
            multi = await tool.invoke(RagSearchInput(query=MULTI_DOC_QUERY))

            return {
                "factual": _capture(factual),
                "multi": _capture(multi),
            }
        finally:
            await adapter.close()

    def _capture(res):
        return {
            "status": res.status.value,
            "intent": res.routing.intent.value if res.routing else None,
            "strategy": res.routing.strategy.value if res.routing else None,
            "fallback_used": res.routing.fallback_used if res.routing else None,
            "chunks": len(res.evidence.chunks),
            "citations": [c.model_dump() for c in res.citations],
            "error": res.error,
        }

    summary = asyncio.run(scenario())

    #: factual -> FOCUSED, query succeeds with evidence + citations
    f = summary["factual"]
    assert f["status"] == RagSearchStatus.SUCCESS.value, f
    assert f["intent"] == RetrievalIntent.FACTUAL.value, f
    assert f["strategy"] == "focused", f
    assert f["fallback_used"] is False, f
    assert f["chunks"] > 0, f
    assert f["citations"], f

    #: multi-document -> HYBRID, query succeeds
    m = summary["multi"]
    assert m["status"] == RagSearchStatus.SUCCESS.value, m
    assert m["intent"] == RetrievalIntent.MULTI_DOCUMENT.value, m
    assert m["strategy"] == "hybrid", m
    assert m["fallback_used"] is False, m
    assert m["chunks"] > 0, m
    assert m["citations"], m
