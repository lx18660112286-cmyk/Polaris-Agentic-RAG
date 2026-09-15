"""RagSearchTool -- agent-facing knowledge retrieval tool.

The Tool is a *Knowledge Retrieval Tool*, NOT a final-answer tool. It
returns structured evidence + citations + diagnostics and lets a future
Agent layer reason and synthesize. It depends only on the
``KnowledgeSearchPort`` abstraction -- never on LightRAG.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

from dev_knowledge_agent.evidence.errors import (
    InvalidKnowledgeQueryError,
    KnowledgeSearchError,
    KnowledgeSearchNotReadyError,
)
from dev_knowledge_agent.evidence.models import (
    Citation,
    Evidence,
    EvidenceAvailability,
    KnowledgeSearchResult,
    RetrievalDiagnostics,
)
from dev_knowledge_agent.protocols.knowledge_search import KnowledgeSearchPort

__all__ = ["RagSearchTool", "RagSearchInput", "RagSearchResult", "RagSearchStatus"]

TOOL_NAME = "search_dev_knowledge"
TOOL_DESCRIPTION = (
    "Search the internal developer knowledge base for deployment, "
    "authentication, incident troubleshooting, and service architecture. "
    "Returns structured evidence, citations, and retrieval diagnostics. "
    "It does not search logs, Git, databases, or the Web."
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
    error: str | None = None


class RagSearchTool:
    """Framework-agnostic search tool bound to a KnowledgeSearchPort."""

    name: str = TOOL_NAME
    description: str = TOOL_DESCRIPTION

    def __init__(self, search_port: KnowledgeSearchPort) -> None:
        #: Accepts anything satisfying the KnowledgeSearchPort protocol
        #: (structural/dynamic satisfaction allowed for fakes and adapters).
        self._search_port = search_port

    @property
    def input_schema(self) -> type[RagSearchInput]:
        return RagSearchInput

    async def invoke(self, input_: RagSearchInput) -> RagSearchResult:
        """Validate the query, run the port, and normalize the result."""
        if not input_.query.strip():
            return RagSearchResult(
                status=RagSearchStatus.ERROR,
                query=input_.query,
                error="Query must not be empty.",
            )

        try:
            result: KnowledgeSearchResult = await self._search_port.search(input_.query)
        except InvalidKnowledgeQueryError as exc:
            return RagSearchResult(status=RagSearchStatus.ERROR, query=input_.query, error=str(exc))
        except KnowledgeSearchNotReadyError as exc:
            return RagSearchResult(status=RagSearchStatus.ERROR, query=input_.query, error=str(exc))
        except KnowledgeSearchError as exc:
            return RagSearchResult(status=RagSearchStatus.ERROR, query=input_.query, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - never let unknown error leak to Agent
            return RagSearchResult(
                status=RagSearchStatus.ERROR,
                query=input_.query,
                error=f"{type(exc).__name__}: {exc}",
            )

        if result.evidence_availability is EvidenceAvailability.NONE:
            return RagSearchResult(
                status=RagSearchStatus.NO_EVIDENCE,
                query=result.query,
                evidence=result.evidence,
                citations=result.citations,
                diagnostics=result.diagnostics,
            )
        return RagSearchResult(
            status=RagSearchStatus.SUCCESS,
            query=result.query,
            evidence=result.evidence,
            citations=result.citations,
            diagnostics=result.diagnostics,
        )
