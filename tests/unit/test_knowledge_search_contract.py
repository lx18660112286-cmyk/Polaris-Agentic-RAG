"""Contract test for KnowledgeSearchPort.

Verifies the abstraction is structural (a duck-typed fake satisfies it
without any LightRAG dependency) and that it does not expose vendor types.
"""

from __future__ import annotations

from polaris_agentic_rag.evidence.models import KnowledgeSearchResult
from polaris_agentic_rag.protocols.knowledge_search import KnowledgeSearchPort
from polaris_agentic_rag.retrieval.models import RetrievalPlan


class FakePort:
    """A duck-typed KnowledgeSearchPort (no LightRAG anywhere)."""

    def __init__(self, result: KnowledgeSearchResult) -> None:
        self.result = result
        self.called_with: list[str] = []

    async def search(
        self, query: str, *, plan: RetrievalPlan | None = None
    ) -> KnowledgeSearchResult:
        self.called_with.append(query)
        return self.result


def test_fake_satisfies_port_contract() -> None:
    port: KnowledgeSearchPort = FakePort(KnowledgeSearchResult(query="q"))  # type: ignore[type-abstract]
    assert isinstance(port, KnowledgeSearchPort)


def test_port_signature_does_not_mention_vendor_types() -> None:
    import inspect
    from typing import get_type_hints

    sig = inspect.signature(KnowledgeSearchPort.search)
    hints = get_type_hints(KnowledgeSearchPort.search)
    assert hints.get("return") is KnowledgeSearchResult
    #: parameters must be just (query, plan); ignore self/builtin binding
    params = [p for p in sig.parameters.values() if p.name not in ("self", "cls")]
    names = [p.name for p in params]
    assert names == ["query", "plan"]
    for p in params:
        if p.name == "query":
            assert p.annotation in ("str", str), p.annotation
        if p.name == "plan":
            #: plan is an application-owned domain type, never a vendor type
            assert p.annotation == "RetrievalPlan | None", p.annotation
    assert "QueryParam" not in str(hints)
    assert "LightRAG" not in str(hints)


def test_result_is_domain_model() -> None:
    result = KnowledgeSearchResult(query="Access token 的有效期是多少？")
    raw = result.model_dump()
    assert "query" in raw
    assert "evidence" in raw
    assert "citations" in raw
    assert "diagnostics" in raw
    assert "evidence_availability" in raw
    #: no vendor keys survive serialization
    for banned in ("mode", "top_k", "QueryParam", "LightRAG"):
        assert banned not in raw


def test_result_rejects_vendor_extra_fields() -> None:
    from pydantic import ValidationError

    try:
        KnowledgeSearchResult(query="q", additional_field="nope")  # type: ignore[call-arg]
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for unexpected field")
