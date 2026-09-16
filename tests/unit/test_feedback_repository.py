"""Offline tests for JsonlFeedbackRepository (spec §8).

Verifies append-only JSONL persistence, retrieval by id, and that the
sanitizer is applied on save so secrets never reach disk.
"""

from __future__ import annotations

import asyncio

from polaris_agentic_rag.flywheel.models import FeedbackEvent, FeedbackType
from polaris_agentic_rag.flywheel.repository import JsonlFeedbackRepository


def _run(coro):
    return asyncio.run(coro)


def test_save_and_list_all(tmp_path) -> None:
    repo = JsonlFeedbackRepository(tmp_path)
    ev = FeedbackEvent(
        feedback_id="fb1", trace_id="t1", query="q", feedback_type=FeedbackType.POSITIVE
    )
    _run(repo.save(ev))
    stored = repo.list_all()
    assert [e.feedback_id for e in stored] == ["fb1"]
    assert stored[0].query == "q"


def test_save_is_append_only_preserves_order(tmp_path) -> None:
    repo = JsonlFeedbackRepository(tmp_path)
    for i in (1, 2, 3):
        _run(
            repo.save(
                FeedbackEvent(
                    feedback_id=f"fb{i}",
                    trace_id=f"t{i}",
                    query=f"q{i}",
                    feedback_type=FeedbackType.INCORRECT,
                )
            )
        )
    assert [e.feedback_id for e in repo.list_all()] == ["fb1", "fb2", "fb3"]


def test_get_returns_event_by_id(tmp_path) -> None:
    repo = JsonlFeedbackRepository(tmp_path)
    _run(
        repo.save(
            FeedbackEvent(
                feedback_id="fb1", trace_id="t1", query="q", feedback_type=FeedbackType.POSITIVE
            )
        )
    )
    got = _run(repo.get("fb1"))
    assert got is not None and got.query == "q"
    assert _run(repo.get("missing")) is None


def test_list_pending_returns_all_currently(tmp_path) -> None:
    #: Stage 5.2 demo: list_pending returns all persisted events.
    repo = JsonlFeedbackRepository(tmp_path)
    _run(
        repo.save(
            FeedbackEvent(
                feedback_id="fb1", trace_id="t1", query="q", feedback_type=FeedbackType.POSITIVE
            )
        )
    )
    assert [e.feedback_id for e in _run(repo.list_pending())] == ["fb1"]


def test_save_sanitizes_secrets_on_disk(tmp_path) -> None:
    repo = JsonlFeedbackRepository(tmp_path)
    _run(
        repo.save(
            FeedbackEvent(
                feedback_id="fb1",
                trace_id="t1",
                query="the key is DEEPSEEK_API_KEY=sk-1234567890abcdef deadbeef",
                feedback_type=FeedbackType.OTHER,
            )
        )
    )
    raw = (tmp_path / "feedback.jsonl").read_text(encoding="utf-8")
    assert "sk-1234567890abcdef" not in raw
    assert "<redacted:secret>" in raw


def test_empty_repo_returns_empty_list(tmp_path) -> None:
    repo = JsonlFeedbackRepository(tmp_path)
    assert repo.list_all() == []


def test_jsonl_file_is_created_under_directory(tmp_path) -> None:
    JsonlFeedbackRepository(tmp_path)
    assert not (tmp_path / "feedback.jsonl").exists()  # lazy: created on save
    repo = JsonlFeedbackRepository(tmp_path)
    _run(
        repo.save(
            FeedbackEvent(
                feedback_id="fb1", trace_id="t1", query="q", feedback_type=FeedbackType.POSITIVE
            )
        )
    )
    assert (tmp_path / "feedback.jsonl").exists()
