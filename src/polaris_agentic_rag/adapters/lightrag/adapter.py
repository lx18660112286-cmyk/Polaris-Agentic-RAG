"""LightRAGAdapter -- application infrastructure wrapping the LightRAG kernel.

Implements ``KnowledgeSearchPort``. Responsibilities:

1. lifecycle state (initialize / search / close)
2. build ``QueryParam`` from adapter settings (never leaks upward)
3. execute ``aquery_data`` (no duplicate ``aquery``+``aquery_data``)
4. validate the raw response
5. call the result mapper
6. normalize LightRAG exceptions into domain exceptions

This is the ONLY production module allowed to import LightRAG.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from lightrag import LightRAG, QueryParam
from lightrag.llm.ollama import ollama_embed
from lightrag.llm.openai import openai_complete_if_cache

from polaris_agentic_rag.adapters.lightrag.mapper import map_query_data_to_result
from polaris_agentic_rag.adapters.lightrag.settings import LightRAGAdapterSettings
from polaris_agentic_rag.adapters.lightrag.source_resolver import SourceResolver
from polaris_agentic_rag.evidence.errors import (
    InvalidKnowledgeQueryError,
    KnowledgeSearchExecutionError,
    KnowledgeSearchNotReadyError,
)
from polaris_agentic_rag.evidence.models import KnowledgeSearchResult
from polaris_agentic_rag.retrieval.models import RetrievalPlan, RetrievalStrategy

__all__ = ["LightRAGAdapter", "build_lightrag"]

DEFAULT_LLM_MODEL = "deepseek-chat"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


async def _deepseek_complete(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
    enable_cot: bool = False,
    keyword_extraction: bool = False,
    entity_extraction: bool = False,
    **kwargs: Any,
) -> str:
    """DeepSeek LLM function in the shape LightRAG expects (OpenAI compat)."""
    if history_messages is None:
        history_messages = []
    kwargs.pop("reasoning_effort", None)
    kwargs.pop("temperature", None)
    raw = await openai_complete_if_cache(
        _env("DKA_LIGHTRAG_LLM_MODEL", DEFAULT_LLM_MODEL),
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        enable_cot=enable_cot,
        keyword_extraction=keyword_extraction,
        entity_extraction=entity_extraction,
        base_url=_env("DKA_LIGHTRAG_LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        api_key=_env("DEEPSEEK_API_KEY"),
        timeout=int(_env("DKA_LIGHTRAG_LLM_TIMEOUT", "1000")),
        extra_body={"thinking": {"type": "disabled"}},
        **kwargs,
    )
    if not isinstance(raw, str):
        raise TypeError(f"unexpected LLM response type: {type(raw).__name__}")
    return raw


def _make_role_llm(
    env_prefix: str, fallback_model: str, fallback_url: str
) -> Callable[..., Awaitable[str]]:
    """Build a role-specific LLM func reading ``{PREFIX}_LLM_MODEL`` /
    ``{PREFIX}_LLM_BINDING_HOST`` / ``{PREFIX}_LLM_BINDING_API_KEY`` / \
    ``{PREFIX}_LLM_TIMEOUT``, falling back to the global settings.

    Registered for LightRAG roles ``keyword`` and ``query`` so the keyword
    extraction and final Q&A phases can each use their own binding, timeout
    and concurrency (``{PREFIX}_MAX_ASYNC_LLM`` is applied at the role layer).
    """

    async def role_complete(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict[str, Any]] | None = None,
        enable_cot: bool = False,
        **kwargs: Any,
    ) -> str:
        if history_messages is None:
            history_messages = []
        kwargs.pop("reasoning_effort", None)
        kwargs.pop("temperature", None)
        kwargs.pop("keyword_extraction", None)
        kwargs.pop("entity_extraction", None)
        raw = await openai_complete_if_cache(
            _env(f"{env_prefix}_LLM_MODEL", fallback_model),
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            enable_cot=enable_cot,
            base_url=_env(f"{env_prefix}_LLM_BINDING_HOST", fallback_url),
            api_key=_env(f"{env_prefix}_LLM_BINDING_API_KEY", _env("DEEPSEEK_API_KEY")),
            timeout=int(
                _env(f"{env_prefix}_LLM_TIMEOUT", _env("DKA_LIGHTRAG_LLM_TIMEOUT", "1000"))
            ),
            extra_body={"thinking": {"type": "disabled"}},
            **kwargs,
        )
        if not isinstance(raw, str):
            raise TypeError(f"unexpected LLM response type: {type(raw).__name__}")
        return raw

    return role_complete


def build_lightrag(working_dir: str | Path, *, workspace: str = "") -> LightRAG:
    """Construct a LightRAG instance wired to DeepSeek + Ollama bge-m3.

    ``workspace`` scopes the kernel's storage namespace (dedup + stores).
    An empty value defers to LightRAG's global ``WORKSPACE`` env / default.

    Role LLMs: the ``keyword`` and ``query`` roles get their own bindings from
    the ``KEYWORD_LLM_*`` / ``QUERY_LLM_*`` env vars (each with its own max
    async / timeout). The remaining ``extract`` / ``vlm`` roles inherit the
    base ``llm_model_func`` and ``MAX_ASYNC_LLM``.
    """
    return LightRAG(
        working_dir=str(working_dir),
        workspace=workspace,
        llm_model_func=_deepseek_complete,
        llm_model_name=_env("DKA_LIGHTRAG_LLM_MODEL", DEFAULT_LLM_MODEL),
        llm_model_max_async=int(_env("MAX_ASYNC_LLM", "4")),
        embedding_func=ollama_embed,
        log_level="INFO",
        role_llm_configs={
            "keyword": {
                "func": _make_role_llm("KEYWORD_LLM", DEFAULT_LLM_MODEL, DEFAULT_LLM_BASE_URL),
                "max_async": int(_env("KEYWORD_MAX_ASYNC_LLM", "2")),
                "timeout": int(_env("KEYWORD_LLM_TIMEOUT", "60")),
            },
            "query": {
                "func": _make_role_llm("QUERY_LLM", DEFAULT_LLM_MODEL, DEFAULT_LLM_BASE_URL),
                "max_async": int(_env("QUERY_MAX_ASYNC_LLM", "2")),
                "timeout": int(_env("QUERY_LLM_TIMEOUT", "120")),
            },
        },
    )


class LightRAGAdapter:
    """Adapter owning the LightRAG kernel lifecycle and the search path."""

    def __init__(
        self,
        working_dir: str | Path | None = None,
        settings: LightRAGAdapterSettings | None = None,
        knowledge_roots: list[Path] | None = None,
        *,
        kernel: LightRAG | None = None,
        resolver: SourceResolver | None = None,
    ) -> None:
        self.settings = settings or LightRAGAdapterSettings()
        self.working_dir = Path(working_dir or self.settings.working_dir)
        self._knowledge_roots = knowledge_roots or [self.working_dir]
        self._resolver = resolver or SourceResolver(self._knowledge_roots)
        #: ``kernel`` is injectable for tests; otherwise built on initialize().
        self._kernel = kernel
        self._initialized = False
        self._closed = False

    @property
    def initialized(self) -> bool:
        """Whether the kernel storages have been initialized."""
        return self._initialized

    async def initialize(self) -> None:
        """Initialize the kernel storages. Idempotent; safe to call twice."""
        if self._initialized:
            return
        if self._closed:
            raise KnowledgeSearchNotReadyError("Adapter has been closed; cannot re-initialize.")
        if self._kernel is None:
            self.working_dir.mkdir(parents=True, exist_ok=True)
            self._kernel = build_lightrag(self.working_dir, workspace=self.settings.workspace)
        self._kernel = self._kernel  #: type narrowing for mypy
        try:
            await self._kernel.initialize_storages()
        except Exception as exc:  # noqa: BLE001 - normalize boundary
            raise KnowledgeSearchExecutionError(f"Failed to initialize storages: {exc}") from exc
        self._initialized = True

    #: Application RetrievalStrategy -> LightRAG query ``mode``. This mapping
    #: is the ONLY place that knows the real mode strings; it never leaves the
    #: adapter package. ``None`` (no plan) falls back to the settings default.
    _STRATEGY_TO_MODE: dict[RetrievalStrategy, str] = {
        RetrievalStrategy.FOCUSED: "local",
        RetrievalStrategy.GLOBAL: "global",
        RetrievalStrategy.HYBRID: "hybrid",
        RetrievalStrategy.VECTOR: "naive",
        RetrievalStrategy.MIXED: "mix",
    }

    def _build_query_param(self, plan: RetrievalPlan | None) -> QueryParam:
        if plan is not None:
            mode = self._STRATEGY_TO_MODE[plan.strategy]
            return QueryParam(
                mode=mode,
                top_k=plan.top_k,
                chunk_top_k=plan.chunk_top_k,
                enable_rerank=plan.enable_rerank,
                include_references=self.settings.include_references,
            )
        return QueryParam(
            mode=self.settings.default_query_mode,
            top_k=self.settings.default_top_k,
            enable_rerank=self.settings.enable_rerank,
            include_references=self.settings.include_references,
        )

    async def search(
        self, query: str, *, plan: RetrievalPlan | None = None
    ) -> KnowledgeSearchResult:
        """Implement KnowledgeSearchPort.search over the real kernel."""
        query = (query or "").strip()
        if not query:
            raise InvalidKnowledgeQueryError("Query must not be empty or whitespace.")
        if not self._initialized or self._closed:
            raise KnowledgeSearchNotReadyError("Knowledge search is not initialized yet.")

        if self._kernel is None:  # pragma: no cover - guarded by _initialized
            raise KnowledgeSearchNotReadyError("Kernel is not available.")

        param = self._build_query_param(plan)
        try:
            raw = await self._kernel.aquery_data(query, param=param)
        except Exception as exc:  # noqa: BLE001 - normalize LightRAG exceptions
            raise KnowledgeSearchExecutionError(f"Kernel query failed: {exc}") from exc

        if not isinstance(raw, dict):
            raise KnowledgeSearchExecutionError(
                f"Kernel returned an unexpected response type: {type(raw).__name__}"
            )

        status = str(raw.get("status", ""))
        if status != "success":
            raise KnowledgeSearchExecutionError(
                f"Kernel query failed with status {status!r}: {raw.get('message')} "
                f"({self._describe_failure(raw)})"
            )

        return map_query_data_to_result(raw, query, self._resolver)

    def _describe_failure(self, raw: dict[str, Any]) -> str:
        metadata = raw.get("metadata") or {}
        reason = metadata.get("failure_reason")
        return f"failure_reason={reason}" if reason else f"message={raw.get('message')}"

    async def close(self) -> None:
        """Finalize kernel storages and mark the adapter closed.

        Safe to call multiple times and usable in try/finally.
        """
        if self._closed:
            return
        if self._kernel is not None:
            try:
                await self._kernel.finalize_storages()
            except Exception as exc:  # noqa: BLE001 - don't mask close path
                raise KnowledgeSearchExecutionError(f"Failed to finalize storages: {exc}") from exc
        self._initialized = False
        self._closed = True
