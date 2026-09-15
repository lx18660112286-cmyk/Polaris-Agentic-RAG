"""Stage 4 real Agent E2E integration test.

Full pipeline: build agent -> initialize LightRAGAdapter -> ingest -> run
Agent (native tool calling, tool_choice=auto) -> close adapter.

Covers:
  A) direct answer (0 RagSearchTool calls)  ["你好，请简单介绍一下你能做什么。"]
  B) tool required                      ["Access token 的有效期是多少？"]
  C) insufficient knowledge             ["Billing Service 使用什么数据库？"]

Semantic-keypoint assertions only (spec §55) -- never exact natural
language. Requires provider credentials (skipped by default).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from polaris_agentic_rag.adapters.lightrag.adapter import LightRAGAdapter
from polaris_agentic_rag.adapters.lightrag.native_baseline import (
    env_vars_available,
    ingest_documents,
)
from polaris_agentic_rag.bootstrap import build_agent
from polaris_agentic_rag.config.settings import get_settings

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KB_FILES = [
    PROJECT_ROOT / "examples" / "knowledge_base" / name
    for name in ("deployment.md", "api_auth.md", "incident_runbook.md", "service_overview.md")
]


def _skip_unless_credentials() -> None:
    if not env_vars_available():
        pytest.skip("Real provider credentials are required (DEEPSEEK_API_KEY)")


def test_agent_e2e(tmp_path: Path) -> None:
    """Build -> init -> ingest -> run 3 real cases -> close."""
    _skip_unless_credentials()
    workdir = tmp_path / "lightrag_stage4"

    from polaris_agentic_rag.adapters.lightrag.settings import LightRAGAdapterSettings

    settings = LightRAGAdapterSettings(
        working_dir=workdir,
        workspace=f"dka_stage4_{workdir.resolve().name}",
    )
    adapter = LightRAGAdapter(
        working_dir=workdir,
        settings=settings,
        knowledge_roots=[PROJECT_ROOT / "examples"],
    )

    async def scenario() -> dict:
        built = build_agent(get_settings(), lightrag_adapter=adapter)
        orchestrator = built.orchestrator
        try:
            await built.adapter.initialize()
            kernel = built.adapter._kernel  # noqa: SLF001 - test probes kernel
            assert kernel is not None
            await ingest_documents(kernel, KB_FILES)

            cases = {
                "direct": "你好，请简单介绍一下你能做什么。",
                "tool": "Access token 的有效期是多少？",
                "unknown": "Billing Service 使用什么数据库？",
            }
            return {name: await orchestrator.run(q) for name, q in cases.items()}
        finally:
            await built.adapter.close()

    results = asyncio.run(scenario())

    #: Case A -- direct answer, no tool call
    a = results["direct"]
    assert a.status.value == "SUCCESS", a.error
    assert a.answer, "direct answer empty"
    assert a.tool_calls == [], f"expected 0 tool calls, got {[t.name for t in a.tool_calls]}"

    #: Case B -- tool required, contains fact + citation
    b = results["tool"]
    assert b.status.value == "SUCCESS", b.error
    assert b.tool_calls, "expected >=1 RagSearchTool call"
    assert any(t.name == "search_dev_knowledge" for t in b.tool_calls)
    assert "30" in b.answer, f"answer missing the fact: {b.answer!r}"
    assert any("api_auth" in c for c in b.citations), f"missing citation: {b.citations}"

    #: Case C -- insufficient knowledge, no invented database
    c = results["unknown"]
    assert c.status.value == "SUCCESS", c.error
    assert c.tool_calls, "expected the tool to be consulted"
    #: NOTE: the kernel may return *some* (irrelevant) evidence for an unknown
    #: entity, so RagSearchTool may legitimately report SUCCESS. The real guard
    #: is that the Agent refuses to invent the database and admits insufficiency.
    _insufficient = any(m in c.answer for m in ("没有", "无法", "不足", "足够", "enough", "信息"))
    assert _insufficient, f"answer must admit lack of knowledge, got: {c.answer!r}"
    assert "Billing Service" in c.answer or "Billing" in c.answer
