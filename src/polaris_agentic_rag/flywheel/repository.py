"""FeedbackRepository (spec §8) + a small JSONL store shared by flywheel data.

``FeedbackRepository`` is a Protocol so a caller or future backend can swap
storage without touching the flywheel. Stage 5.2 ships ``JsonlFeedbackRepository``
persisting to ``.local/feedback/feedback.jsonl`` (gitignored). No database
(spec §8).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from polaris_agentic_rag.flywheel.models import FeedbackEvent
from polaris_agentic_rag.flywheel.sanitizer import sanitize_text

__all__ = [
    "FeedbackRepository",
    "JsonlFeedbackRepository",
    "JsonlStore",
]


@runtime_checkable
class FeedbackRepository(Protocol):
    """Persists and reads FeedbackEvents (spec §8)."""

    async def save(self, event: FeedbackEvent) -> None: ...

    async def get(self, feedback_id: str) -> FeedbackEvent | None: ...

    async def list_pending(self) -> list[FeedbackEvent]: ...

    def list_all(self) -> list[FeedbackEvent]:
        """Return every persisted event (sync convenience for reports/metrics)."""
        ...


class JsonlStore:
    """Append-only, gitignored JSONL store for one kind of flywheel record.

    Records are keyed by a stable ``id`` field name; load is lazy and
    append is synchronous. Simple and cheap enough for a local demo
    (spec §16/§23).
    """

    def __init__(self, path: str | Path, *, id_field: str = "id", model: type) -> None:
        self._path = Path(path)
        self._id_field = id_field
        self._model = model

    @property
    def path(self) -> Path:
        return self._path

    def _read_raw(self) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        out: list[dict[str, Any]] = []
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                out.append(json.loads(stripped))
        return out

    def read(self) -> list[Any]:
        """Return all records in append order."""
        return [self._model(**item) for item in self._read_raw()]

    def get(self, record_id: str) -> Any:
        for item in self._read_raw():
            if item.get(self._id_field) == record_id:
                return self._model(**item)
        return None

    def append(self, record: Any) -> None:
        """Serialize ``record`` (a pydantic model or dict) to one JSON line."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(record, "model_dump_json"):
            line = record.model_dump_json()
        else:
            line = json.dumps(record, ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def replace(self, records: list[Any]) -> None:
        """Rewrite the whole store (used to persist status transitions)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines = [r.model_dump_json() for r in records]
        self._path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


class JsonlFeedbackRepository:
    """FeedbackRepository implemented over a JSONL file (spec §8).

    Every saved event is passed through :func:`sanitize_text` so secrets
    never reach disk (spec §40/§41). ``list_pending`` returns all events
    that still need review (only negative feedback is reviewable).
    """

    def __init__(self, directory: str | Path) -> None:
        self._store = JsonlStore(
            Path(directory) / "feedback.jsonl",
            id_field="feedback_id",
            model=FeedbackEvent,
        )

    async def save(self, event: FeedbackEvent) -> None:
        sanitized = event.model_copy(
            update={
                "query": sanitize_text(event.query),
                "answer": sanitize_text(event.answer),
                "comment": sanitize_text(event.comment or "") or None,
                "citations": [sanitize_text(c) for c in event.citations],
            }
        )
        self._store.append(sanitized)

    async def get(self, feedback_id: str) -> FeedbackEvent | None:
        return cast(FeedbackEvent | None, self._store.get(feedback_id))

    async def list_pending(self) -> list[FeedbackEvent]:
        return self._store.read()

    def list_all(self) -> list[FeedbackEvent]:
        return self._store.read()
