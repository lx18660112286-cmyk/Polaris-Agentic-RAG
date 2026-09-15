"""Agent domain models (framework/provider-neutral).

These are the application's own types for the Agent layer. They never
import provider SDKs (openai / AsyncOpenAI) or LightRAG. The
``DeepSeekAgentModelAdapter`` translates these to/from the provider's
wire types; the orchestrator only ever sees these.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from dev_knowledge_agent.retrieval.models import RoutingDecision, RoutingStep

__all__ = [
    "AgentRole",
    "AgentToolCall",
    "AgentMessage",
    "AgentModelResponse",
    "AgentStatus",
    "AgentResult",
    "TokenUsage",
    "ToolCallRecord",
    "format_tool_result_for_model",
]


class AgentRole(str, Enum):
    """Role of a message in the agent conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentToolCall(BaseModel):
    """A model-requested tool invocation (provider-neutral)."""

    id: str
    name: str
    raw_arguments: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentMessage(BaseModel):
    """A single message in the agent conversation."""

    role: AgentRole
    content: str | None = None
    #: Only on ASSISTANT messages: tool calls the model wants executed.
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    #: Only on TOOL messages: the id this result answers.
    tool_call_id: str | None = None


class TokenUsage(BaseModel):
    """Provider-neutral token counts (spec §30).

    ``None`` means the provider did not return this number; do not estimate
    it and pretend it is real usage.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class AgentModelResponse(BaseModel):
    """The provider-neutral result of one model completion."""

    content: str | None = None
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    #: Real provider usage when the provider supplies it (spec §29/§30).
    usage: TokenUsage | None = None


class AgentStatus(str, Enum):
    """Terminal status of an Agent run."""

    SUCCESS = "SUCCESS"
    TOOL_ERROR = "TOOL_ERROR"
    MAX_STEPS_EXCEEDED = "MAX_STEPS_EXCEEDED"
    MODEL_ERROR = "MODEL_ERROR"


class ToolCallRecord(BaseModel):
    """Observable record of one tool call (for Stage 5 observability).

    ``sources`` are the source names the tool cited in its result;
    ``routing`` is the RetrievalPlan's RoutingDecision when the tool
    surfaces one (RagSearchTool does). Both are evaluation inputs.
    """

    name: str
    arguments: dict[str, Any]
    result_status: str = ""
    error: str | None = None
    duration_ms: float | None = None
    sources: list[str] = Field(default_factory=list)
    routing: RoutingDecision | None = None


class AgentResult(BaseModel):
    """Application-level result of an Agent run."""

    status: AgentStatus
    answer: str = ""
    citations: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    steps: int = 0
    error: str | None = None
    #: Correlation id shared by Agent -> Tool -> Router -> Adapter (spec §24).
    trace_id: str | None = None
    #: Immutable query provenance (Stage 5.1, spec §9): the exact user message
    #: the request started with. Never mutated by the Agent loop.
    original_query: str = ""
    #: Every routing decision produced during this request, in order. A later
    #: step never overwrites an earlier one (Stage 5 last-write-wins artifact
    #: removed, spec §6-§8). Primary = the first step (first successful
    #: knowledge-search call).
    routing_steps: list[RoutingStep] = Field(default_factory=list)


def _extract_citations(value: Any) -> list[str]:
    """Collect citation source names from a tool result that carries them."""
    citations = getattr(value, "citations", None)
    if not citations:
        return []
    out: list[str] = []
    for c in citations:
        name = getattr(c, "source_name", None)
        if name:
            out.append(str(name))
    #: preserve order, drop duplicates
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def format_tool_result_for_model(value: Any) -> str:
    """Serialize a tool result into a compact, model-consumable text block.

    RagSearch-like results (with ``status`` / ``query`` / ``evidence`` /
    ``citations``) are rendered as a readable evidence summary so the Agent
    can ground its answer and cite sources. Other values fall back to JSON.
    """
    if isinstance(value, str):
        return value

    status = getattr(value, "status", None)
    citations = _extract_citations(value)

    if status is not None:
        parts: list[str] = [f"tool={getattr(value, 'query', '')!r} status={status}"]
        if getattr(value, "routing", None) is not None:
            routing = value.routing
            parts.append(f"intent={routing.intent.value} strategy={routing.strategy.value}")
        error = getattr(value, "error", None)
        evidence = getattr(value, "evidence", None)
        if evidence is not None:
            parts.append(
                f"chunks={len(evidence.chunks)} "
                f"entities={len(evidence.entities)} relationships={len(evidence.relationships)}"
            )
        #: include the actual evidence text so the Agent can ground its answer.
        if evidence is not None and status != "NO_EVIDENCE":
            chunks = getattr(evidence, "chunks", None) or []
            for i, chunk in enumerate(chunks[:5], start=1):
                chunk_content = (getattr(chunk, "content", None) or "").strip().replace("\n", " ")
                chunk_src = getattr(chunk, "source_name", None)
                parts.append(f"chunk[{i}] ({chunk_src}): {chunk_content}")
            entities = getattr(evidence, "entities", None) or []
            for ent in entities[:10]:
                name = getattr(ent, "entity_name", "") or ""
                desc = (getattr(ent, "description", None) or "").strip().replace("\n", " ")
                parts.append(f"entity[{name}]: {desc}")
            relationships = getattr(evidence, "relationships", None) or []
            for rel in relationships[:10]:
                parts.append(
                    f"rel[{getattr(rel, 'src_id', '')}] -> [{getattr(rel, 'tgt_id', '')}]: "
                    f"{(getattr(rel, 'description', None) or '').strip().replace(chr(10), ' ')}"
                )
        if citations:
            parts.append("citations=" + ", ".join(citations))
        if error:
            parts.append(f"error={error}")
        return "\n".join(parts)

    if isinstance(value, BaseModel):
        import json

        return json.dumps(value.model_dump(), ensure_ascii=False)
    return str(value)
