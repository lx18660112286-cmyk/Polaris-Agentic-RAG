"""Static tests for the Agent system prompt (spec §56)."""

from __future__ import annotations

from pydantic import BaseModel

from polaris_agentic_rag.agent.prompts import build_system_prompt


class _Tool:
    name = "search_dev_knowledge"
    description = "desc"

    @property
    def input_schema(self) -> type[BaseModel]:
        class _In(BaseModel):
            query: str

        return _In

    async def invoke(self, input_: BaseModel) -> str:  # pragma: no cover
        return ""


def test_system_prompt_contains_policy_markers() -> None:
    prompt = build_system_prompt(_Tool())
    required = [
        "search_dev_knowledge",  # internal knowledge -> tool
        "NO_EVIDENCE",  # no evidence -> do not invent
        "ERROR",  # error -> do not invent
        "[api_auth.md]",  # citation format example
        "not invent",  # grounding
        "generic programming knowledge",  # not-for example
    ]
    for marker in required:
        assert marker in prompt, f"prompt missing marker: {marker!r}"


def test_system_prompt_explicitly_excludes_kernel_params() -> None:
    prompt = build_system_prompt(_Tool())
    #: concrete kernel values must never appear as claimed/shown to the user
    for marker in ("hybrid", "local", "global", "top_k=20"):
        assert marker not in prompt, f"prompt must not expose kernel value: {marker!r}"
    #: the prompt must explicitly forbid exposing retrieval parameters
    assert "Do not expose internal retrieval parameters" in prompt
