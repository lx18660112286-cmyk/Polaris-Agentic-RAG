"""Unit test for RagSearchTool with a fake port.

This test proves the architecture: the tool is tied to the Port abstraction
and does not require LightRAG to run. This protects the inversion of
control and dependency inversion.
"""

from __future__ import annotations

from dev_knowledge_agent.evidence.errors import InvalidKnowledgeQueryError
from dev_knowledge_agent.evidence.models import EvidenceAvailability, KnowledgeSearchResult
from dev_knowledge_agent.protocols.knowledge_search import KnowledgeSearchPort
from dev_knowledge_agent.retrieval.models import RetrievalPlan
from dev_knowledge_agent.retrieval.router import QueryRouter
from dev_knowledge_agent.tools.rag_search import RagSearchInput, RagSearchStatus, RagSearchTool


class FakeKnowledgeSearchPort(KnowledgeSearchPort):
    """Fake port that returns canned results."""

    def __init__(
        self,
        result: KnowledgeSearchResult | None = None,
        raise_exception: Exception | None = None,
    ) -> None:
        self._result = result
        self._raise_exception = raise_exception
        self.received_plans: list[RetrievalPlan | None] = []

    async def search(
        self, query: str, *, plan: RetrievalPlan | None = None
    ) -> KnowledgeSearchResult:
        self.received_plans.append(plan)
        if self._raise_exception:
            raise self._raise_exception
        if self._result:
            return self._result
        return KnowledgeSearchResult(
            query=query, evidence_availability=EvidenceAvailability.PRESENT
        )


def _make_tool(port: FakeKnowledgeSearchPort) -> RagSearchTool:
    return RagSearchTool(search_port=port, router=QueryRouter())


async def test_tool_invoke_success() -> None:
    fake_result = KnowledgeSearchResult(
        query="Access token 的有效期是多少？",
        evidence_availability=EvidenceAvailability.PRESENT,
    )
    fake_port = FakeKnowledgeSearchPort(result=fake_result)
    tool = _make_tool(fake_port)
    input_ = RagSearchInput(query="Access token 的有效期是多少？")
    result = await tool.invoke(input_)
    assert result.status == RagSearchStatus.SUCCESS
    assert result.error is None
    assert result.query == "Access token 的有效期是多少？"


async def test_tool_invoke_no_evidence() -> None:
    fake_result = KnowledgeSearchResult(
        query="foo", evidence_availability=EvidenceAvailability.NONE
    )
    fake_port = FakeKnowledgeSearchPort(result=fake_result)
    tool = _make_tool(fake_port)
    input_ = RagSearchInput(query="foo")
    result = await tool.invoke(input_)
    assert result.status == RagSearchStatus.NO_EVIDENCE
    assert result.error is None


async def test_tool_invoke_error_catches_domain_exception() -> None:
    fake_port = FakeKnowledgeSearchPort(raise_exception=InvalidKnowledgeQueryError("empty"))
    tool = _make_tool(fake_port)
    input_ = RagSearchInput(query="x")
    result = await tool.invoke(input_)
    assert result.status == RagSearchStatus.ERROR
    assert result.error is not None


async def test_tool_invoke_error_catches_unknown_exception() -> None:
    msg = "something bad happened"
    fake_port = FakeKnowledgeSearchPort(raise_exception=RuntimeError(msg))
    tool = _make_tool(fake_port)
    input_ = RagSearchInput(query="x")
    result = await tool.invoke(input_)
    assert result.status == RagSearchStatus.ERROR
    assert "RuntimeError" in result.error
    assert msg in result.error


async def test_tool_passes_router_plan_to_port() -> None:
    fake_port = FakeKnowledgeSearchPort(
        result=KnowledgeSearchResult(
            query="Access token 的有效期是多少？",
            evidence_availability=EvidenceAvailability.PRESENT,
        )
    )
    tool = _make_tool(fake_port)
    input_ = RagSearchInput(query="Access token 的有效期是多少？")
    result = await tool.invoke(input_)
    assert result.status == RagSearchStatus.SUCCESS
    #: the Tool forwarded a Router-generated plan to the Port (not None)
    assert len(fake_port.received_plans) == 1
    assert fake_port.received_plans[0] is not None
    #: routing decision is surfaced for observability
    assert result.routing is not None
    assert result.routing.strategy.value == "focused"


def test_input_rejects_empty_query() -> None:
    from pydantic import ValidationError

    try:
        RagSearchInput(query="   ")
    except ValidationError:
        return
    raise AssertionError("Expected empty whitespace query to fail validation")


def test_tool_exports_metadata() -> None:
    from dev_knowledge_agent.tools.rag_search import TOOL_DESCRIPTION, TOOL_NAME

    tool = RagSearchTool(search_port=FakeKnowledgeSearchPort(), router=QueryRouter())
    assert tool.name == TOOL_NAME
    assert tool.description == TOOL_DESCRIPTION
    assert tool.input_schema is RagSearchInput
