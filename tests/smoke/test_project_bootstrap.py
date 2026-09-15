"""Smoke tests: project bootstrap prerequisites."""

from __future__ import annotations

import re
from pathlib import Path

from polaris_agentic_rag.config.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DOCS = (
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/ROADMAP.md",
    "docs/LIGHTRAG_SOURCE_INTEGRATION.md",
    "docs/adr/0001-lightrag-as-rag-kernel.md",
)

REQUIRED_DIRS = (
    "docs",
    "docs/adr",
    "examples",
    "examples/knowledge_base",
    "scripts",
    "src",
    "src/polaris_agentic_rag",
    "src/polaris_agentic_rag/config",
    "src/polaris_agentic_rag/protocols",
    "src/polaris_agentic_rag/adapters",
    "src/polaris_agentic_rag/adapters/lightrag",
    "src/polaris_agentic_rag/tools",
    "src/polaris_agentic_rag/evidence",
    "src/polaris_agentic_rag/router",
    "src/polaris_agentic_rag/agent",
    "src/polaris_agentic_rag/evaluation",
    "src/polaris_agentic_rag/observability",
    "tests",
    "tests/architecture",
    "tests/smoke",
)

EXAMPLE_KNOWLEDGE_FILES = (
    "deployment.md",
    "api_auth.md",
    "incident_runbook.md",
    "service_overview.md",
)


def test_package_importable() -> None:
    import polaris_agentic_rag  # noqa: F401

    assert polaris_agentic_rag.__version__  # type: ignore[attr-defined]


def test_settings_instantiable() -> None:
    settings = Settings()
    assert settings.app_name == "dev-knowledge-agent"
    assert settings.lightrag_integration_mode == "source_sdk"


def test_required_docs_exist() -> None:
    missing = [doc for doc in REQUIRED_DOCS if not (PROJECT_ROOT / doc).is_file()]
    assert not missing, f"Missing required docs: {missing}"


def test_required_directories_exist() -> None:
    missing = [d for d in REQUIRED_DIRS if not (PROJECT_ROOT / d).is_dir()]
    assert not missing, f"Missing required directories: {missing}"


def test_example_knowledge_files_exist() -> None:
    kb_dir = PROJECT_ROOT / "examples" / "knowledge_base"
    missing = [f for f in EXAMPLE_KNOWLEDGE_FILES if not (kb_dir / f).is_file()]
    assert not missing, f"Missing example knowledge files: {missing}"


def test_lightrag_submodule_path_exists() -> None:
    submodule_dir = PROJECT_ROOT / "third_party" / "LightRAG"
    assert submodule_dir.is_dir(), "third_party/LightRAG submodule directory is missing"
    assert (submodule_dir / "pyproject.toml").is_file() or (submodule_dir / "setup.py").is_file()


def test_no_secrets_in_example_env() -> None:
    """Placeholder-only rule: real-looking provider keys must not be committed."""
    env_example = PROJECT_ROOT / ".env.example"
    if not env_example.exists():
        return
    content = env_example.read_text(encoding="utf-8")
    #: deepseek-style keys are lowercase hex after sk-; 'x' placeholders are fine
    assert not re.search(r"sk-[0-9a-fA-F]{20,}", content), (
        "real-looking API key found in .env.example"
    )
