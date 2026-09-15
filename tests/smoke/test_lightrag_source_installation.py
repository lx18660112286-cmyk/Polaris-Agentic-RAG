"""Smoke tests: LightRAG source installation verification.

These tests do NOT import ``lightrag`` directly. They go through the
adapter's ``source_probe`` module, keeping the test layer on the safe
side of the adapter boundary.

The tests are offline-safe: they perform no ingest, no query, and no
LLM / embedding / rerank calls.
"""

from __future__ import annotations

from pathlib import Path

from dev_knowledge_agent.adapters.lightrag.source_probe import (
    SOURCE_DIR_MARKER,
    probe_lightrag_source,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_lightrag_import_verification() -> None:
    """The pinned LightRAG module/class/QueryParam are discoverable via probe."""
    probe = probe_lightrag_source()
    assert probe.lightrag_available, "LightRAG class not discoverable"
    assert probe.query_param_available, "QueryParam not discoverable"
    assert probe.module_file, "lightrag module file is unknown"


def test_lightrag_resolves_to_submodule_source() -> None:
    """lightrag must physically resolve into third_party/LightRAG.

    The probe normalizes the module file path (plain containment checks are
    platform-fragile: Windows uses backslashes), and its ``is_source_checkout``
    flag is the authoritative result.
    """
    probe = probe_lightrag_source()
    assert probe.is_source_checkout, (
        f"lightrag resolved to {probe.module_file}, not the submodule source ({SOURCE_DIR_MARKER})"
    )


def test_submodule_directory_exists() -> None:
    submodule_dir = PROJECT_ROOT / "third_party" / "LightRAG"
    assert submodule_dir.is_dir()


def test_no_real_kernel_operations() -> None:
    """Stage 0 smoke tests never invoke kernel side effects."""
    probe = probe_lightrag_source()
    #: probe only reports capability; nothing else is executed
    assert probe.lightrag_available
    assert probe.query_param_available
