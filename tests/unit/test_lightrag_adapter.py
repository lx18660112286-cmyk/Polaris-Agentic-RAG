"""Unit tests for LightRAGAdapter lifecycle and exception normalization.

These use a stub kernel so no real provider is needed. The tests live in
tests/unit but the adapter module correctly lives in the allowed LightRAG
boundary (tests may import it freely to exercise it offline).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from dev_knowledge_agent.adapters.lightrag.adapter import LightRAGAdapter
from dev_knowledge_agent.adapters.lightrag.settings import LightRAGAdapterSettings
from dev_knowledge_agent.evidence.errors import (
    InvalidKnowledgeQueryError,
    KnowledgeSearchExecutionError,
    KnowledgeSearchNotReadyError,
)
from dev_knowledge_agent.evidence.models import EvidenceAvailability


@dataclass
class StubKernel:
    """Stands in for a LightRAG instance (records calls)."""

    initialized: bool = False
    finalized: bool = False
    query_response: dict | None = None
    raise_exception: Exception | None = None
    searched: list[str] = field(default_factory=list)

    async def initialize_storages(self) -> None:
        self.initialized = True

    async def finalize_storages(self) -> None:
        self.finalized = True

    async def aquery_data(self, query: str, param=None) -> dict:
        self.searched.append(query)
        if self.raise_exception:
            raise self.raise_exception
        if self.query_response is not None:
            return self.query_response
        return {
            "status": "success",
            "message": "ok",
            "data": {"entities": [], "relationships": [], "chunks": [], "references": []},
            "metadata": {"query_mode": "hybrid"},
        }


async def test_search_before_initialize_raises_not_ready() -> None:
    kernel = StubKernel()
    adapter = LightRAGAdapter(kernel=kernel)
    with pytest.raises(KnowledgeSearchNotReadyError):
        await adapter.search("Access token 的有效期是多少？")


async def test_initialize_then_search_succeeds() -> None:
    kernel = StubKernel()
    adapter = LightRAGAdapter(kernel=kernel)
    await adapter.initialize()
    result = await adapter.search("Access token 的有效期是多少？")
    assert adapter.initialized
    assert kernel.searched == ["Access token 的有效期是多少？"]
    assert result.query == "Access token 的有效期是多少？"
    assert result.evidence_availability is EvidenceAvailability.NONE


async def test_initialize_is_idempotent() -> None:
    kernel = StubKernel()
    adapter = LightRAGAdapter(kernel=kernel)
    await adapter.initialize()
    await adapter.initialize()
    #: initialize_storages is only called on the first initialize
    assert adapter.initialized


async def test_empty_query_raises_invalid_query() -> None:
    kernel = StubKernel()
    adapter = LightRAGAdapter(kernel=kernel)
    await adapter.initialize()
    with pytest.raises(InvalidKnowledgeQueryError):
        await adapter.search("   ")


async def test_kernel_exception_is_normalized() -> None:
    kernel = StubKernel(raise_exception=RuntimeError("boom"))
    adapter = LightRAGAdapter(kernel=kernel)
    await adapter.initialize()
    with pytest.raises(KnowledgeSearchExecutionError):
        await adapter.search("q")


async def test_failure_status_raises_execution_error() -> None:
    kernel = StubKernel(
        query_response={
            "status": "failure",
            "message": "No relevant document chunks found.",
            "data": {},
            "metadata": {"failure_reason": "no_results"},
        }
    )
    adapter = LightRAGAdapter(kernel=kernel)
    await adapter.initialize()
    with pytest.raises(KnowledgeSearchExecutionError):
        await adapter.search("q")


async def test_close_finalizes_and_blocks_search() -> None:
    kernel = StubKernel()
    adapter = LightRAGAdapter(kernel=kernel)
    await adapter.initialize()
    await adapter.close()
    assert kernel.finalized
    assert not adapter.initialized
    with pytest.raises(KnowledgeSearchNotReadyError):
        await adapter.search("q")


async def test_close_is_idempotent() -> None:
    kernel = StubKernel()
    adapter = LightRAGAdapter(kernel=kernel)
    await adapter.initialize()
    await adapter.close()
    await adapter.close()
    #: finalize_storages only called once
    assert kernel.finalized


async def test_settings_drive_query_param_mode() -> None:
    kernel = StubKernel()
    seen_params: list = []

    async def capturing_aquery_data(query: str, param=None) -> dict:
        seen_params.append(param)
        return {
            "status": "success",
            "message": "ok",
            "data": {"entities": [], "relationships": [], "chunks": [], "references": []},
            "metadata": {"query_mode": "naive"},
        }

    kernel.aquery_data = capturing_aquery_data  # type: ignore[method-assign]
    settings = LightRAGAdapterSettings(default_query_mode="naive", default_top_k=7)
    adapter = LightRAGAdapter(kernel=kernel, settings=settings)
    await adapter.initialize()
    await adapter.search("q")
    assert len(seen_params) == 1
    assert seen_params[0].mode == "naive"
    assert seen_params[0].top_k == 7
    assert seen_params[0].enable_rerank is False
    assert seen_params[0].include_references is True
