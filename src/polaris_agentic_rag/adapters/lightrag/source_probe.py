"""Source probe for the pinned LightRAG checkout.

This module performs source inspection / runtime introspection ONLY. It
does NOT implement any RAG business logic and does NOT execute queries,
ingestion, or any model calls.

The probe answers "what does the pinned LightRAG source actually expose"
so that the adapter and the smoke tests do not hard-code assumptions.
"""

from __future__ import annotations

import ast
import importlib
import importlib.metadata as importlib_metadata
import inspect
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Marker used to verify the import physically resolves to the submodule
#: checkout (``third_party/LightRAG``).
SOURCE_DIR_MARKER = "third_party/LightRAG"


def _safe_import(module_name: str) -> Any:
    """Import a module and return it, or None if import fails."""
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


@dataclass(frozen=True)
class LightRAGSourceProbe:
    """Snapshot of LightRAG facts discovered from the pinned source."""

    lightrag_available: bool = False
    query_param_available: bool = False
    module_file: str | None = None
    package_path: str | None = None
    package_version: str | None = None
    class_location: str | None = None
    query_param_location: str | None = None
    is_source_checkout: bool = False
    source_dir_marker: str = SOURCE_DIR_MARKER

    has_insert: bool = False
    has_ainsert: bool = False
    has_query: bool = False
    has_aquery: bool = False
    has_query_data: bool = False
    has_aquery_data: bool = False

    mode_annotation: str | None = None
    query_mode_choices: list[str] = field(default_factory=list)

    query_param_fields: dict[str, bool] = field(default_factory=dict)
    captured_constructor_callables: list[str] = field(default_factory=list)
    storage_methods: list[str] = field(default_factory=list)


def _as_showable(obj: Any) -> str | None:
    """Return the file where an object is defined, if determinable."""
    try:
        return inspect.getsourcefile(obj) or None
    except TypeError:
        return None


def _extract_literal_choices(annotation: Any) -> list[str]:
    """Extract string choices from a typing.Literal annotation.

    Handles both live ``Literal[...]`` types and their string form (e.g.
    ``"Literal['local', 'global', ...]"`` produced by deferred annotations).
    """
    if isinstance(annotation, str):
        try:
            text = annotation.strip()
            if text.startswith("Literal["):
                text = text[len("Literal[") : -1] if text.endswith("]") else text
                parsed = ast.literal_eval(f"[{text}]")
                if isinstance(parsed, list):
                    scalar = (str, int, float, bool)
                    return [str(item) for item in parsed if isinstance(item, scalar)]
        except (ValueError, SyntaxError):
            return []
        return []
    try:
        args = typing.get_args(annotation)
    except Exception:
        return []
    return [str(a) for a in args if isinstance(a, str)]


def _collect_query_param_fields(query_param_class: Any) -> dict[str, bool]:
    """Collect existence of the QueryParam fields we care about."""
    annotations = getattr(query_param_class, "__annotations__", {}) or {}
    model_fields = getattr(query_param_class, "model_fields", None) or {}
    fields_of_interest = (
        "only_need_context",
        "only_need_prompt",
        "include_references",
        "enable_rerank",
        "top_k",
        "chunk_top_k",
    )
    result: dict[str, bool] = {}
    for field_name in fields_of_interest:
        result[field_name] = (
            field_name in annotations
            or field_name in model_fields
            or hasattr(query_param_class, field_name)
        )
    return result


def probe_lightrag_source() -> LightRAGSourceProbe:
    """Introspect the pinned LightRAG source and return the findings.

    Offline-safe: importing LightRAG performs no network or model calls.
    """
    lightrag = _safe_import("lightrag")
    if lightrag is None:
        return LightRAGSourceProbe()

    lightrag_module_file = str(getattr(lightrag, "__file__", ""))
    lightrag_module_path = Path(lightrag_module_file)
    package_path = str(lightrag_module_path.parent) if lightrag_module_file else None
    normalized_module_file = (
        lightrag_module_path.resolve().as_posix() if lightrag_module_file else ""
    )

    package_version: str | None = None
    for dist_name in ("lightrag-hku", "lightrag", "LightRAG"):
        try:
            package_version = importlib_metadata.version(dist_name)
            break
        except importlib_metadata.PackageNotFoundError:
            continue

    lightrag_class = getattr(lightrag, "LightRAG", None)
    query_param_class = getattr(lightrag, "QueryParam", None)

    has_methods: dict[str, bool] = {}
    for method in ("insert", "ainsert", "query", "aquery", "query_data", "aquery_data"):
        has_methods[f"has_{method}"] = bool(
            lightrag_class is not None and callable(getattr(lightrag_class, method, None))
        )

    constructor_callables: list[str] = []
    storage_methods: list[str] = []
    if lightrag_class is not None:
        init_signature = inspect.signature(lightrag_class.__init__)
        for param_name in (
            "llm_model_func",
            "llm_model_name",
            "keyword_extraction_func",
            "embedding_func",
        ):
            if param_name in init_signature.parameters:
                constructor_callables.append(param_name)
        for method in ("initialize_storages", "finalize_storages"):
            if callable(getattr(lightrag_class, method, None)):
                storage_methods.append(method)

    mode_annotation: str | None = None
    query_mode_choices: list[str] = []
    query_param_fields: dict[str, bool] = {}
    if query_param_class is not None:
        annotations = getattr(query_param_class, "__annotations__", {}) or {}
        raw_annotation = annotations.get("mode")
        if raw_annotation is not None:
            mode_annotation = str(raw_annotation)
            query_mode_choices = _extract_literal_choices(raw_annotation)
        query_param_fields = _collect_query_param_fields(query_param_class)

    return LightRAGSourceProbe(
        lightrag_available=lightrag_class is not None,
        query_param_available=query_param_class is not None,
        module_file=lightrag_module_file or None,
        package_path=package_path,
        package_version=package_version,
        class_location=_as_showable(lightrag_class),
        query_param_location=_as_showable(query_param_class),
        is_source_checkout=SOURCE_DIR_MARKER in normalized_module_file,
        has_insert=has_methods["has_insert"],
        has_ainsert=has_methods["has_ainsert"],
        has_query=has_methods["has_query"],
        has_aquery=has_methods["has_aquery"],
        has_query_data=has_methods["has_query_data"],
        has_aquery_data=has_methods["has_aquery_data"],
        mode_annotation=mode_annotation,
        query_mode_choices=query_mode_choices,
        query_param_fields=query_param_fields,
        captured_constructor_callables=constructor_callables,
        storage_methods=storage_methods,
    )


def describe_source_probe(probe: LightRAGSourceProbe) -> dict[str, Any]:
    """Return a dict representation of the probe for documentation."""
    return {
        "lightrag_available": probe.lightrag_available,
        "query_param_available": probe.query_param_available,
        "module_file": probe.module_file,
        "package_path": probe.package_path,
        "package_version": probe.package_version,
        "class_location": probe.class_location,
        "query_param_location": probe.query_param_location,
        "is_source_checkout": probe.is_source_checkout,
        "has_insert": probe.has_insert,
        "has_ainsert": probe.has_ainsert,
        "has_query": probe.has_query,
        "has_aquery": probe.has_aquery,
        "has_query_data": probe.has_query_data,
        "has_aquery_data": probe.has_aquery_data,
        "mode_annotation": probe.mode_annotation,
        "query_mode_choices": probe.query_mode_choices,
        "query_param_fields": probe.query_param_fields,
        "storage_methods": probe.storage_methods,
    }
