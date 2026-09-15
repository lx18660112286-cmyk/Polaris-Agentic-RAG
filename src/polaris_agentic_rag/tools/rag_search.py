"""RagSearchTool -- agent-facing knowledge retrieval tool.

The Tool is a *Knowledge Retrieval Tool*, NOT a final-answer tool. It
returns structured evidence + citations + diagnostics and lets a future
Agent layer reason and synthesize. It depends only on the
``KnowledgeSearchPort`` abstraction -- never on LightRAG.
"""

from __future__ import annotations

import time
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from polaris_agentic_rag.evidence.errors import (
    InvalidKnowledgeQueryError,
    KnowledgeSearchError,
    KnowledgeSearchNotReadyError,
)
from polaris_agentic_rag.evidence.models import (
    Citation,
    Evidence,
    EvidenceAvailability,
    KnowledgeSearchResult,
    RetrievalDiagnostics,
)
from polaris_agentic_rag.observability.models import FailureCategory, TraceEventType
from polaris_agentic_rag.observability.tracer import Tracer
from polaris_agentic_rag.protocols.knowledge_search import KnowledgeSearchPort
from polaris_agentic_rag.retrieval.models import RoutingDecision
from polaris_agentic_rag.retrieval.router import QueryRouter
from polaris_agentic_rag.tools.errors import InvalidToolArgumentsError
from polaris_agentic_rag.tools.protocol import ToolDefinition

__all__ = [
    "RagSearchTool",
    "RagSearchInput",
    "RagSearchResult",
    "RagSearchStatus",
    "AgentRagSearchTool",
]

TOOL_NAME = "search_dev_knowledge"
TOOL_DESCRIPTION = (
    "Search the internal developer knowledge base about: "
    "deployment, authentication / access tokens, production incidents / "
    "runbooks, and service architecture & dependencies. Returns structured "
    "evidence plus source citations. "
    "Do NOT use it for general conversation, arithmetic, generic programming "
    "knowledge, or external web facts."
)


class RagSearchInput(BaseModel):
    """Agent-facing input for RagSearchTool. Deliberately minimal."""

    query: str = Field(..., min_length=1, description="The knowledge query to search.")

    @field_validator("query")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be empty or whitespace")
        return value


class RagSearchStatus(str, Enum):
    """Tool-level status of a search invocation."""

    SUCCESS = "SUCCESS"
    NO_EVIDENCE = "NO_EVIDENCE"
    ERROR = "ERROR"


class RagSearchResult(BaseModel):
    """Tool-facing result, layered on the Port result."""

    status: RagSearchStatus
    query: str
    evidence: Evidence = Field(default_factory=Evidence)
    citations: list[Citation] = Field(default_factory=list)
    diagnostics: RetrievalDiagnostics = Field(default_factory=RetrievalDiagnostics)
    routing: RoutingDecision | None = None
    error: str | None = None


class RagSearchTool:
    """Framework-agnostic search tool bound to a KnowledgeSearchPort + QueryRouter.

    The Tool accepts only ``query`` (RagSearchInput). It delegates the
    retrieval decision to the ``QueryRouter``, which produces an
    application-owned ``RetrievalPlan`` that is passed to the Port. Neither
    the Tool nor the Agent controls ``mode/top_k/rerank``.
    """

    name: str = TOOL_NAME
    description: str = TOOL_DESCRIPTION

    def __init__(
        self,
        search_port: KnowledgeSearchPort,
        *,
        router: QueryRouter,
        tracer: Tracer | None = None,
    ) -> None:
        #: Accepts anything satisfying the KnowledgeSearchPort protocol
        #: (structural/dynamic satisfaction allowed for fakes and adapters).
        self._search_port = search_port
        self._router = router
        self._tracer = tracer

    @property
    def input_schema(self) -> type[RagSearchInput]:
        return RagSearchInput

    @property
    def router(self) -> QueryRouter:
        """The router this tool delegates retrieval decisions to.

        Read-only access for component-level evaluation (Stage 5.1 spec §3):
        routing the *original* dataset query directly, bypassing the Agent
        and tool calling, to isolate QueryRouter quality.
        """
        return self._router

    def _emit(self, event_type: TraceEventType, **attributes: object) -> None:
        if self._tracer is None:
            return
        #: attach the executing tool call id so ROUTER_DECISION / RETRIEVAL
        #: events correlate with TOOL_CALL_* without position guessing (§20).
        tool_call_id = self._tracer.current_tool_call_id
        if tool_call_id is not None:
            attributes.setdefault("tool_call_id", tool_call_id)
        self._tracer.emit(event_type, **attributes)  # type: ignore[arg-type]

    async def invoke(self, input_: RagSearchInput) -> RagSearchResult:
        """Validate the query, route it, run the port, and normalize the result."""
        if not input_.query.strip():
            return RagSearchResult(
                status=RagSearchStatus.ERROR,
                query=input_.query,
                error="Query must not be empty.",
            )

        plan = self._router.route(input_.query)
        routing = self._router.last_decision
        if routing is not None:
            #: Router trace: only the deterministic rule outcome (spec §26); never CoT.
            self._emit(
                TraceEventType.ROUTER_DECISION,
                query=input_.query,
                intent=routing.intent.value,
                strategy=routing.strategy.value,
                reason=routing.reason,
                fallback_used=routing.fallback_used,
            )

        start = time.perf_counter()
        self._emit(
            TraceEventType.RETRIEVAL_STARTED,
            query=input_.query,
            strategy=plan.strategy.value,
        )
        try:
            result: KnowledgeSearchResult = await self._search_port.search(input_.query, plan=plan)
        except (
            InvalidKnowledgeQueryError,
            KnowledgeSearchNotReadyError,
            KnowledgeSearchError,
        ) as exc:
            self._emit(
                TraceEventType.RETRIEVAL_COMPLETED,
                strategy=plan.strategy.value,
                latency_ms=round((time.perf_counter() - start) * 1000.0, 3),
                error=str(exc),
            )
            self._emit(
                TraceEventType.ERROR,
                category=FailureCategory.RETRIEVAL_ERROR.value,
                error=str(exc),
            )
            return RagSearchResult(status=RagSearchStatus.ERROR, query=input_.query, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - never let unknown error leak to Agent
            self._emit(
                TraceEventType.RETRIEVAL_COMPLETED,
                strategy=plan.strategy.value,
                latency_ms=round((time.perf_counter() - start) * 1000.0, 3),
                error=f"{type(exc).__name__}: {exc}",
            )
            self._emit(
                TraceEventType.ERROR,
                category=FailureCategory.RETRIEVAL_ERROR.value,
                error=f"{type(exc).__name__}: {exc}",
            )
            return RagSearchResult(
                status=RagSearchStatus.ERROR,
                query=input_.query,
                error=f"{type(exc).__name__}: {exc}",
            )

        #: Retrieval trace: counts only, never raw evidence text (spec §28).
        self._emit(
            TraceEventType.RETRIEVAL_COMPLETED,
            strategy=plan.strategy.value,
            evidence_availability=result.evidence_availability.value,
            chunk_count=len(result.evidence.chunks),
            entity_count=len(result.evidence.entities),
            relationship_count=len(result.evidence.relationships),
            citation_count=len(result.citations),
            latency_ms=round((time.perf_counter() - start) * 1000.0, 3),
        )

        if result.evidence_availability is EvidenceAvailability.NONE:
            return RagSearchResult(
                status=RagSearchStatus.NO_EVIDENCE,
                query=result.query,
                evidence=result.evidence,
                citations=result.citations,
                diagnostics=result.diagnostics,
                routing=routing,
            )
        return RagSearchResult(
            status=RagSearchStatus.SUCCESS,
            query=result.query,
            evidence=result.evidence,
            citations=result.citations,
            diagnostics=result.diagnostics,
            routing=routing,
        )


class AgentRagSearchTool:
    """Thin AgentTool-compatible wrapper around RagSearchTool (spec §15).

    Adapts ``RagSearchTool`` to the generic ``AgentTool`` surface without
    rewriting it, so the Tool contract (Stage 2/3) stays untouched. The
    registry builds the validated ``RagSearchInput`` from ``input_schema``
    and this wrapper narrows it back before delegating.
    """

    name: str = TOOL_NAME
    description: str = TOOL_DESCRIPTION

    def __init__(self, tool: RagSearchTool) -> None:
        self._tool = tool

    @property
    def input_schema(self) -> type[RagSearchInput]:
        return RagSearchInput

    def as_tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=RagSearchInput,
        )

    async def invoke(self, input_: object) -> RagSearchResult:
        if not isinstance(input_, RagSearchInput):
            raise InvalidToolArgumentsError(
                f"Tool {self.name!r} expects RagSearchInput, got {type(input_).__name__}"
            )
        return await self._tool.invoke(input_)
