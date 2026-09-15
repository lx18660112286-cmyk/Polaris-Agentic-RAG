"""SourceResolver -- map a citation basename to a project source path.

LightRAG normalizes ``file_path`` to a basename (e.g. ``api_auth.md``)
for citations. We must NOT simply assume ``knowledge_root / basename``
is unique. The resolver scans allowed knowledge roots and reports a
three-state outcome:

* RESOLVED   -- exactly one match
* UNRESOLVED -- no match
* AMBIGUOUS  -- more than one file shares the basename; we never silently
                pick one
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from polaris_agentic_rag.evidence.models import SourceResolutionStatus

__all__ = ["SourceResolver", "Resolution"]


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving one basename."""

    basename: str
    status: SourceResolutionStatus
    paths: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def resolved_path(self) -> Path | None:
        """The unique matched path, or ``None`` unless RESOLVED."""
        if self.status is SourceResolutionStatus.RESOLVED and len(self.paths) == 1:
            return self.paths[0]
        return None


class SourceResolver:
    """Resolve basenames against a set of allowed knowledge roots."""

    def __init__(self, knowledge_roots: list[Path]) -> None:
        if not knowledge_roots:
            raise ValueError("SourceResolver requires at least one knowledge root")
        self._roots: list[Path] = [root.expanduser().resolve() for root in knowledge_roots]

    def resolve(self, basename: str | None) -> Resolution:
        """Resolve a single basename to a unique path, if unambiguous."""
        if not basename or not basename.strip():
            return Resolution(basename=basename or "", status=SourceResolutionStatus.UNRESOLVED)

        matches: list[Path] = []
        for root in self._roots:
            for candidate in root.rglob(basename):
                if candidate.is_file():
                    matches.append(candidate.resolve())
        #: de-duplicate (a file could be reachable from overlapping roots)
        seen: set[Path] = set()
        unique: list[Path] = []
        for path in matches:
            if path not in seen:
                seen.add(path)
                unique.append(path)

        if len(unique) == 1:
            return Resolution(
                basename=basename,
                status=SourceResolutionStatus.RESOLVED,
                paths=(unique[0],),
            )
        if len(unique) > 1:
            return Resolution(
                basename=basename,
                status=SourceResolutionStatus.AMBIGUOUS,
                paths=tuple(sorted(unique)),
            )
        return Resolution(basename=basename, status=SourceResolutionStatus.UNRESOLVED)
