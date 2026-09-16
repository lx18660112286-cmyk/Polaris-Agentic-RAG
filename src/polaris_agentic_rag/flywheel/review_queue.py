"""ReviewQueue -- file-backed queue of ReviewCandidates (spec §16-§19).

Persists ``ReviewCandidate`` records under ``.local/review/`` (gitignored)
using a single JSONL file whose ``status`` field carries the lifecycle
(``PENDING -> IN_REVIEW -> ACCEPTED/REJECTED/NO_ACTION/PROPOSAL_CREATED``).

Human review is a mandatory gate (spec §19): no runtime/method call here
auto-applies a proposal or mutates any production artifact.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from polaris_agentic_rag.flywheel.ids import utc_now_iso
from polaris_agentic_rag.flywheel.models import ReviewCandidate, ReviewStatus
from polaris_agentic_rag.flywheel.repository import JsonlStore

__all__ = ["ReviewQueue"]


class ReviewQueue:
    """Add / query / transition ReviewCandidates backed by a JSONL store."""

    def __init__(self, directory: str | Path) -> None:
        self._store = JsonlStore(
            Path(directory) / "review.jsonl",
            id_field="candidate_id",
            model=ReviewCandidate,
        )

    @property
    def path(self) -> Path:
        return self._store.path

    def add(self, candidate: ReviewCandidate) -> None:
        """Queue one candidate for human review."""
        self._store.append(candidate)

    def get(self, candidate_id: str) -> ReviewCandidate | None:
        return cast(ReviewCandidate | None, self._store.get(candidate_id))

    def list_all(self, status: ReviewStatus | None = None) -> list[ReviewCandidate]:
        records: list[ReviewCandidate] = self._store.read()
        if status is None:
            return records
        return [c for c in records if c.status is status]

    def list_pending(self) -> list[ReviewCandidate]:
        return [c for c in self.list_all() if c.status is ReviewStatus.PENDING]

    def update(
        self,
        candidate_id: str,
        *,
        status: ReviewStatus,
        category: object | None = None,
        failure_layer: object | None = None,
        notes: str | None = None,
        reviewed_by: str | None = None,
    ) -> ReviewCandidate | None:
        """Transition one candidate and merge review verdicts into it.

        Fields left as ``None`` are preserved. Returns the updated candidate
        (or ``None`` if the id was not found).
        """
        records: list[ReviewCandidate] = self._store.read()
        updated: ReviewCandidate | None = None
        for i, record in enumerate(records):
            if record.candidate_id != candidate_id:
                continue
            update: dict[str, object] = {"status": status, "reviewed_at": utc_now_iso()}
            if category is not None:
                update["category"] = category
            if failure_layer is not None:
                update["failure_layer"] = failure_layer
            if notes is not None:
                update["notes"] = notes
            if reviewed_by is not None:
                update["reviewed_by"] = reviewed_by
            records[i] = record.model_copy(update=update)
            updated = records[i]
            break
        if updated is None:
            return None
        self._store.replace(records)
        return updated
