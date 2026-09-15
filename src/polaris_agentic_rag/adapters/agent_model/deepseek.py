"""DeepSeek Agent Model Adapter (OpenAI-compatible).

The ONLY place in the agent path allowed to import the provider SDK
(``openai``). It implements ``AgentModelPort`` by translating:

    our AgentMessage       <->  openai chat messages
    our ToolDefinition     ->   openai function tool schema
    openai ChatCompletion  ->   our AgentModelResponse

The adapter reads ``DEEPSEEK_API_KEY`` from the environment (never
hardcoded / committed). Agent LLM wiring is independent of the LightRAG
kernel's internal LLM wiring.
"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from polaris_agentic_rag.agent.models import (
    AgentMessage,
    AgentModelResponse,
    AgentToolCall,
    TokenUsage,
)
from polaris_agentic_rag.tools.protocol import ToolDefinition

__all__ = ["DeepSeekAgentModelAdapter"]


class DeepSeekAgentModelError(Exception):
    """Provider-level failure from the DeepSeek/OpenAI call."""


def _to_provider_message(msg: AgentMessage) -> dict[str, Any]:
    """Convert an AgentMessage into an OpenAI-compatible chat message."""
    role = msg.role.value
    base: dict[str, Any]
    if role == "assistant":
        base = {"role": "assistant", "content": msg.content or None}
        if msg.tool_calls:
            base["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.raw_arguments or "{}",
                    },
                }
                for tc in msg.tool_calls
            ]
        return base
    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": msg.tool_call_id or "",
            "content": msg.content or "",
        }
    return {"role": role, "content": msg.content or ""}


def _to_provider_tool(td: ToolDefinition) -> dict[str, Any]:
    """Convert a provider-neutral ToolDefinition into an OpenAI tool schema."""
    schema = td.parameters.model_json_schema()
    #: OpenAI expects a JSON-serializable schema; translate pydantic $defs into
    #: the provider's type/schema shape is unnecessary here (single string arg).
    return {
        "type": "function",
        "function": {
            "name": td.name,
            "description": td.description,
            "parameters": schema,
        },
    }


class DeepSeekAgentModelAdapter:
    """AgentModelPort over DeepSeek's OpenAI-compatible chat API."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "",
        )

    async def complete(
        self,
        messages: list[AgentMessage],
        tools: list[ToolDefinition],
    ) -> AgentModelResponse:
        """Run one completion; return the provider-neutral response."""
        from openai import AuthenticationError, InternalServerError, NotFoundError

        provider_messages = [_to_provider_message(m) for m in messages]
        provider_tools = [_to_provider_tool(t) for t in tools]

        request: dict[str, Any] = {
            "model": self._model,
            "messages": provider_messages,
            "temperature": self._temperature,
            "tool_choice": "auto",
        }
        if provider_tools:
            request["tools"] = provider_tools

        try:
            resp = await self._client.chat.completions.create(**request)
        except (AuthenticationError, NotFoundError, InternalServerError) as exc:
            #: normalize provider errors into our own; never leak SDK shape up.
            raise DeepSeekAgentModelError(f"DeepSeek/OpenAI request failed: {exc}") from exc

        choice = resp.choices[0] if resp.choices else None
        if choice is None:
            raise DeepSeekAgentModelError("DeepSeek/OpenAI returned no choices")

        content = choice.message.content
        tool_calls = choice.message.tool_calls or []
        parsed_calls: list[AgentToolCall] = []
        for tc in tool_calls:
            if tc.type != "function" or not tc.function:
                continue
            parsed_calls.append(
                AgentToolCall(
                    id=tc.id or "",
                    name=tc.function.name or "",
                    raw_arguments=tc.function.arguments or "{}",
                )
            )

        #: Real provider usage (spec §29/§30); never estimated, None when absent.
        usage = getattr(resp, "usage", None)
        usage_model = None
        if usage is not None:
            usage_model = TokenUsage(
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
            )

        return AgentModelResponse(
            content=content,
            tool_calls=parsed_calls,
            finish_reason=choice.finish_reason,
            usage=usage_model,
        )
