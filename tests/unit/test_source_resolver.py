"""Unit tests for SourceResolver (unique / missing / collision)."""

from __future__ import annotations

from pathlib import Path

from dev_knowledge_agent.adapters.lightrag.source_resolver import SourceResolver
from dev_knowledge_agent.evidence.models import SourceResolutionStatus


def test_resolves_unique_basename(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    (root / "api_auth.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "api_auth.md").write_text("x", encoding="utf-8")
    resolver = SourceResolver([root])

    res = resolver.resolve("api_auth.md")
    assert res.status is SourceResolutionStatus.RESOLVED
    assert res.resolved_path == (root / "api_auth.md").resolve()


def test_missing_basename_is_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    root.mkdir(parents=True, exist_ok=True)
    resolver = SourceResolver([root])

    res = resolver.resolve("does_not_exist.md")
    assert res.status is SourceResolutionStatus.UNRESOLVED
    assert res.resolved_path is None


def test_collision_is_ambiguous_not_silently_resolved(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    (root / "sub1").mkdir(parents=True, exist_ok=True)
    (root / "sub2").mkdir(parents=True, exist_ok=True)
    (root / "sub1" / "deployment.md").write_text("a", encoding="utf-8")
    (root / "sub2" / "deployment.md").write_text("b", encoding="utf-8")
    resolver = SourceResolver([root])

    res = resolver.resolve("deployment.md")
    assert res.status is SourceResolutionStatus.AMBIGUOUS
    assert len(res.paths) == 2
    assert res.resolved_path is None  # must not silently pick one


def test_blank_basename_is_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    root.mkdir(parents=True, exist_ok=True)
    resolver = SourceResolver([root])
    assert resolver.resolve("").status is SourceResolutionStatus.UNRESOLVED
    assert resolver.resolve(None).status is SourceResolutionStatus.UNRESOLVED


def test_empty_roots_rejected() -> None:
    try:
        SourceResolver([])
    except ValueError:
        return
    raise AssertionError("Expected ValueError for empty knowledge roots")
