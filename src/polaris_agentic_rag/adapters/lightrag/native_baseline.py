"""Stage 1 Native LightRAG Baseline Harness.

This module is the Stage 1 harness (NOT the final ``LightRAGAdapter``).
It exists only to validate the pinned LightRAG kernel E2E over the
example knowledge base: construct -> initialize storages -> ingest ->
query / aquery_data -> finalize storages.

It lives under ``adapters/lightrag/`` on purpose: this is the only place
allowed to touch LightRAG imports.

Provider wiring (env-driven, no hardcoded secrets):
- LLM: DeepSeek via OpenAI-compatible client (``DEEPSEEK_API_KEY``).
- Embedding: local Ollama (``ollama_embed``, model from env).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lightrag import LightRAG, QueryParam
from lightrag.llm.ollama import ollama_embed
from lightrag.llm.openai import openai_complete_if_cache

#: Common defaults shared by the harness.
DEFAULT_LLM_MODEL = "deepseek-chat"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_EMBED_MODEL = "bge-m3:latest"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"

QUERY_MODES = ("local", "global", "hybrid", "naive", "mix")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_vars_available() -> bool:
    """True when real provider credentials are configured in the environment."""
    return bool(_env("DEEPSEEK_API_KEY"))


def required_env_vars() -> list[str]:
    """Environment variables needed to run the Stage 1 E2E baseline."""
    return ["DEEPSEEK_API_KEY", "DKA_LIGHTRAG_LLM_MODEL", "DKA_LIGHTRAG_EMBED_MODEL"]


async def deepseek_complete(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
    enable_cot: bool = False,
    keyword_extraction: bool = False,
    entity_extraction: bool = False,
    **kwargs: Any,
) -> str:
    """DeepSeek LLM function in the shape LightRAG expects."""
    if history_messages is None:
        history_messages = []
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
        **kwargs,
    )
    if not isinstance(raw, str):
        raise TypeError(f"unexpected LLM response type: {type(raw).__name__}")
    return raw


def build_lightrag(working_dir: str | Path) -> LightRAG:
    """Construct a LightRAG instance wired to DeepSeek + Ollama bge-m3."""
    return LightRAG(
        working_dir=str(working_dir),
        llm_model_func=deepseek_complete,
        llm_model_name=_env("DKA_LIGHTRAG_LLM_MODEL", DEFAULT_LLM_MODEL),
        embedding_func=ollama_embed,
        log_level="INFO",
    )


@dataclass
class QueryObservation:
    """Transparent record of one baseline query execution."""

    case_id: str = ""
    query: str = ""
    mode: str = ""
    latency_s: float = 0.0
    answer: str = ""
    answered: bool = False
    error: str | None = None
    data_status: str | None = None
    entities: int = 0
    relationships: int = 0
    chunks: int = 0
    references: list[dict[str, Any]] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    mode_keywords: dict[str, Any] = field(default_factory=dict)
    processing_info: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


async def run_query(
    rag: LightRAG,
    query: str,
    *,
    mode: str,
    include_references: bool = True,
    top_k: int = 20,
    enable_rerank: bool = False,
) -> QueryObservation:
    """Run one aquery + aquery_data pair and record the observation."""
    obs = QueryObservation(query=query, mode=mode)
    param = QueryParam(
        mode=mode,
        top_k=top_k,
        enable_rerank=enable_rerank,
        include_references=include_references,
    )
    start = time.perf_counter()
    try:
        answer = await rag.aquery(query, param=param)
        obs.answer = str(answer)
        obs.answered = bool(answer and str(answer).strip())
        latency_query = time.perf_counter() - start

        start = time.perf_counter()
        data = await rag.aquery_data(query, param=param)
        obs.latency_s = latency_query + (time.perf_counter() - start)
    except Exception as exc:  # noqa: BLE001 - record the real kernel failure shape
        obs.latency_s = time.perf_counter() - start
        obs.error = f"{type(exc).__name__}: {exc}"
        return obs

    if not isinstance(data, dict):
        obs.error = f"aquery_data returned unexpected type: {type(data).__name__}"
        return obs

    obs.data_status = str(data.get("status"))
    data_block = data.get("data") or {}
    obs.entities = len(data_block.get("entities") or [])
    obs.relationships = len(data_block.get("relationships") or [])
    obs.chunks = len(data_block.get("chunks") or [])
    obs.references = [dict(r) for r in (data_block.get("references") or [])]
    obs.source_files = sorted(
        {str(r.get("file_path", "")) for r in obs.references if r.get("file_path")}
    )
    metadata = data.get("metadata") or {}
    obs.mode_keywords = dict(metadata.get("keywords") or {})
    obs.processing_info = dict(metadata.get("processing_info") or {})
    return obs


async def ingest_documents(rag: LightRAG, doc_paths: list[Path]) -> dict[str, Any]:
    """Ingest legal documents as vector-only chunks first.

    process_options="F!" means:
    - F: fixed-token chunking
    - !: skip entity/relation extraction, do not build knowledge graph
    """
    contents: list[str] = [p.read_text(encoding="utf-8") for p in doc_paths]
    start = time.perf_counter()

    await rag.ainsert(
        contents,
        file_paths=[str(p) for p in doc_paths],
        
    )

    elapsed = time.perf_counter() - start
    return {"documents": len(doc_paths), "duration_s": elapsed}


async def run_native_lifecycle(
    working_dir: str | Path,
    doc_paths: list[Path],
    queries: list[dict[str, Any]],
    modes: tuple[str, ...] = QUERY_MODES,
) -> dict[str, Any]:
    """Execute the full Stage 1 lifecycle and return observations.

    finalize_storages() is guaranteed via try/finally.
    """
    working_dir = Path(working_dir)
    working_dir.mkdir(parents=True, exist_ok=True)
    rag = build_lightrag(working_dir)

    result: dict[str, Any] = {
        "working_dir": str(working_dir),
        "llm_model": _env("DKA_LIGHTRAG_LLM_MODEL", DEFAULT_LLM_MODEL),
        "embed_model": _env("DKA_LIGHTRAG_EMBED_MODEL", DEFAULT_EMBED_MODEL),
        "lifecycle": {},
        "ingestion": {},
        "queries": [],
    }
    try:
        t0 = time.perf_counter()
        await rag.initialize_storages()
        result["lifecycle"]["initialize_storages_s"] = round(time.perf_counter() - t0, 2)
        result["lifecycle"]["initialize_ok"] = True

        result["ingestion"] = await ingest_documents(rag, doc_paths)
        result["ingestion"]["success"] = True

        observations: list[QueryObservation] = []
        for item in queries:
            query_text = str(item["query"])
            case_id = str(item.get("case_id", "?"))
            if len(modes) == 1:
                obs = await run_query(rag, query_text, mode=modes[0])
                obs.case_id = case_id
                observations.append(obs)
            else:
                for mode in modes:
                    obs = await run_query(rag, query_text, mode=mode)
                    obs.case_id = f"{case_id}[{mode}]"
                    observations.append(obs)
        result["queries"] = [vars(o) for o in observations]
    finally:
        await rag.finalize_storages()
        result["lifecycle"]["finalize_ok"] = True
    return result
