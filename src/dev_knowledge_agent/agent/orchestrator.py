"""AgentOrchestrator -- minimal native tool-calling Agent loop.

Implements a small, clear state machine (spec §51: no Agent framework)
around a provider-neutral ``AgentModelPort`` and a ``ToolRegistry``:

    system -> user -> model
        ├─ no tool_calls -> final answer
        └─ tool_calls
             ├─ max_tool_calls / max_steps / duplicate guards
             └─ validate + ToolRegistry.invoke -> append tool result -> model
             then final answer or more tool calls

The orchestrator depends only on protocols/agent + tools; never on a
provider SDK (openai) or LightRAG. Stage 5 adds optional low-intrusion
tracing: when a ``Tracer`` is injected, every run emits an ordered,
secret-safe ``TraceEvent`` stream (spec §25/§49) and the resulting
``AgentResult.trace_id`` correlates the whole Agent -> Tool -> Router ->
Adapter chain.
"""

from __future__ import annotations

import json
import time

from dev_knowledge_agent.agent.errors import AgentMaxStepsExceededError
from dev_knowledge_agent.agent.models import (
    AgentMessage,
    AgentModelResponse,
    AgentResult,
    AgentRole,
    AgentStatus,
    ToolCallRecord,
    _extract_citations,
    format_tool_result_for_model,
)
from dev_knowledge_agent.observability.models import FailureCategory, TraceEventType
from dev_knowledge_agent.observability.tracer import Tracer
from dev_knowledge_agent.protocols.agent_model import AgentModelPort
from dev_knowledge_agent.tools.errors import (
    InvalidToolArgumentsError,
    ToolError,
    UnknownToolError,
)
from dev_knowledge_agent.tools.registry import ToolRegistry

__all__ = ["AgentOrchestrator"]

#: Cap on the user query recorded in AGENT_STARTED (keep traces small).
_TRACE_QUERY_CAP = 500


def _call_signature(name: str, raw_arguments: str) -> str:
    try:
        normalized = json.dumps(
            json.loads(raw_arguments or "{}"), sort_keys=True, ensure_ascii=False
        )
    except json.JSONDecodeError:
        normalized = raw_arguments
    return f"{name}|{normalized}"


class AgentOrchestrator:
    """Runs the Agent Loop against a ToolRegistry + AgentModelPort."""

    def __init__(
        self,
        model: AgentModelPort,
        registry: ToolRegistry,
        *,
        system_prompt: str,
        max_steps: int,
        max_tool_calls: int,
        tracer: Tracer | None = None,
    ) -> None:
        self._model = model
        self._registry = registry
        self._system_prompt = system_prompt
        self._max_steps = max_steps
        self._max_tool_calls = max_tool_calls
        self._tracer = tracer

    def _emit(self, event_type: TraceEventType, **attributes: object) -> None:
        if self._tracer is not None:
            self._tracer.emit(event_type, **attributes)  # type: ignore[arg-type]

    async def run(self, user_message: str) -> AgentResult:
        """Run the loop for one user message and return an AgentResult."""
        messages: list[AgentMessage] = [
            AgentMessage(role=AgentRole.SYSTEM, content=self._system_prompt),
            AgentMessage(role=AgentRole.USER, content=user_message),
        ]
        records: list[ToolCallRecord] = []
        result_citations: list[str] = []
        seen_calls: set[str] = set()
        tool_calls_used = 0
        steps = 0
        trace_id: str | None = None

        if self._tracer is not None:
            trace_id = self._tracer.start_trace()
            self._emit(TraceEventType.AGENT_STARTED, query=user_message[:_TRACE_QUERY_CAP])

        try:
            while True:
                steps += 1
                if steps > self._max_steps:
                    raise AgentMaxStepsExceededError(f"Agent exceeded max_steps={self._max_steps}")

                definitions = self._registry.definitions()
                model_start = time.perf_counter()
                self._emit(
                    TraceEventType.MODEL_CALL_STARTED,
                    step=steps,
                    tool_count=len(definitions),
                )
                response = await self._model.complete(messages, definitions)
                usage = response.usage
                self._emit(
                    TraceEventType.MODEL_CALL_COMPLETED,
                    step=steps,
                    latency_ms=round((time.perf_counter() - model_start) * 1000.0, 3),
                    tool_call_count=len(response.tool_calls),
                    input_tokens=usage.input_tokens if usage else None,
                    output_tokens=usage.output_tokens if usage else None,
                    total_tokens=usage.total_tokens if usage else None,
                )

                if not response.tool_calls:
                    return self._finish(
                        trace_id=trace_id,
                        status=AgentStatus.SUCCESS,
                        answer=self._answer_text(response),
                        citations=result_citations,
                        records=records,
                        steps=steps,
                    )

                messages.append(
                    AgentMessage(
                        role=AgentRole.ASSISTANT,
                        content=response.content,
                        tool_calls=response.tool_calls,
                    )
                )

                for tc in response.tool_calls:
                    if tool_calls_used >= self._max_tool_calls:
                        error = f"Agent exceeded max_tool_calls={self._max_tool_calls}"
                        self._emit(
                            TraceEventType.ERROR,
                            category=FailureCategory.MAX_TOOL_CALLS.value,
                            error=error,
                        )
                        return self._finish(
                            trace_id=trace_id,
                            status=AgentStatus.TOOL_ERROR,
                            error=error,
                            records=records,
                            steps=steps,
                        )
                    tool_calls_used += 1

                    self._emit(
                        TraceEventType.TOOL_SELECTED,
                        name=tc.name,
                        arguments=tc.raw_arguments,
                    )

                    signature = _call_signature(tc.name, tc.raw_arguments)
                    if signature in seen_calls:
                        records.append(
                            ToolCallRecord(
                                name=tc.name,
                                arguments=tc.arguments,
                                result_status="duplicate",
                                error="repeat identical tool call rejected",
                            )
                        )
                        messages.append(
                            self._tool_message(
                                tc.id,
                                "Rejected: this tool call is a duplicate of a "
                                "previous identical call.",
                            )
                        )
                        continue
                    seen_calls.add(signature)

                    content, record, citations = await self._run_tool(
                        tc.id, tc.name, tc.raw_arguments
                    )
                    records.append(record)
                    result_citations.extend(citations)
                    messages.append(self._tool_message(tc.id, content))
        except AgentMaxStepsExceededError as exc:
            self._emit(
                TraceEventType.ERROR,
                category=FailureCategory.MAX_STEPS.value,
                error=str(exc),
            )
            return self._finish(
                trace_id=trace_id,
                status=AgentStatus.MAX_STEPS_EXCEEDED,
                error=str(exc),
                records=records,
                steps=steps,
            )
        except Exception as exc:  # noqa: BLE001 - normalize model failures
            self._emit(
                TraceEventType.ERROR,
                category=FailureCategory.MODEL_ERROR.value,
                error=f"{type(exc).__name__}: {exc}",
            )
            return self._finish(
                trace_id=trace_id,
                status=AgentStatus.MODEL_ERROR,
                error=f"{type(exc).__name__}: {exc}",
                records=records,
                steps=steps,
            )
        finally:
            if self._tracer is not None and trace_id is not None:
                self._tracer.end_trace()

    def _finish(
        self,
        *,
        trace_id: str | None,
        status: AgentStatus,
        records: list[ToolCallRecord],
        steps: int,
        answer: str = "",
        error: str | None = None,
        citations: list[str] | None = None,
    ) -> AgentResult:
        """Emit AGENT_COMPLETED and build the final AgentResult."""
        final_citations = sorted(set(citations or []))
        self._emit(
            TraceEventType.AGENT_COMPLETED,
            status=status.value,
            steps=steps,
            answer_len=len(answer),
            citations=final_citations,
            error=error,
        )
        return AgentResult(
            status=status,
            answer=answer,
            citations=final_citations,
            tool_calls=records,
            steps=steps,
            error=error,
            trace_id=trace_id,
        )

    async def _run_tool(
        self,
        tool_call_id: str,
        name: str,
        raw_arguments: str,
    ) -> tuple[str, ToolCallRecord, list[str]]:
        """Validate + invoke one tool call; return (model_content, record, citations)."""
        del tool_call_id  #: not needed by the registry
        start = time.perf_counter()
        self._emit(TraceEventType.TOOL_CALL_STARTED, name=name)
        record = ToolCallRecord(name=name, arguments={})
        citations: list[str] = []
        content = ""
        try:
            outcome = await self._registry.invoke(name, raw_arguments)
            record.arguments = outcome.value.query if hasattr(outcome.value, "query") else {}
            raw_status = getattr(outcome.value, "status", None)
            #: RagSearchStatus is an Enum -> use its .value ("SUCCESS"/"NO_EVIDENCE")
            record.result_status = str(getattr(raw_status, "value", raw_status) or "ok")
            citations = _extract_citations(outcome.value)
            record.sources = list(citations)
            record.routing = getattr(outcome.value, "routing", None)
            content = format_tool_result_for_model(outcome.value)
        except UnknownToolError as exc:
            record.result_status = "unknown_tool"
            record.error = str(exc)
            content = f"Unknown tool: {exc}."
        except InvalidToolArgumentsError as exc:
            record.result_status = "invalid_arguments"
            record.error = str(exc)
            content = f"Invalid tool arguments: {exc}."
        except ToolError as exc:
            record.result_status = "error"
            record.error = str(exc)
            content = f"Tool invocation failed: {exc}."
        except Exception as exc:  # noqa: BLE001 - never leak a traceback to the model
            record.result_status = "error"
            record.error = f"{type(exc).__name__}: {exc}"
            content = f"Tool invocation failed: {record.error}."
        record.duration_ms = round((time.perf_counter() - start) * 1000.0, 3)
        self._emit(
            TraceEventType.TOOL_CALL_COMPLETED,
            name=name,
            result_status=record.result_status,
            duration_ms=record.duration_ms,
            error=record.error,
        )
        return content, record, citations

    @staticmethod
    def _answer_text(response: AgentModelResponse) -> str:
        return (response.content or "").strip()

    @staticmethod
    def _tool_message(tool_call_id: str, content: str) -> AgentMessage:
        return AgentMessage(
            role=AgentRole.TOOL,
            content=content,
            tool_call_id=tool_call_id,
        )
