"""Offline tests for ReviewQueue (spec §16-§19).

Verifies JSONL persistence, PENDING listing, and status transitions that
record ``reviewed_at`` (human review is the mandatory gate).
"""

from __future__ import annotations

from polaris_agentic_rag.flywheel.ids import make_id
from polaris_agentic_rag.flywheel.models import (
    ImprovementCategory,
    ReviewCandidate,
    ReviewPriority,
    ReviewSource,
    ReviewStatus,
)
from polaris_agentic_rag.flywheel.review_queue import ReviewQueue


def _candidate(cid: str = "c1", status: ReviewStatus = ReviewStatus.PENDING) -> ReviewCandidate:
    return ReviewCandidate(
        candidate_id=cid,
        trace_id="t1",
        source=ReviewSource.RUNTIME_SIGNAL,
        reason="no evidence",
        priority=ReviewPriority.MEDIUM,
        status=status,
    )


def test_add_and_get(tmp_path) -> None:
    queue = ReviewQueue(tmp_path)
    cand = _candidate()
    queue.add(cand)
    got = queue.get("c1")
    assert got is not None and got.candidate_id == "c1"
    assert queue.get("missing") is None


def test_list_all_filters_by_status(tmp_path) -> None:
    queue = ReviewQueue(tmp_path)
    queue.add(_candidate("c1", ReviewStatus.PENDING))
    queue.add(_candidate("c2", ReviewStatus.ACCEPTED))
    pending = queue.list_all(status=ReviewStatus.PENDING)
    assert [c.candidate_id for c in pending] == ["c1"]


def test_list_pending(tmp_path) -> None:
    queue = ReviewQueue(tmp_path)
    queue.add(_candidate("c1", ReviewStatus.PENDING))
    queue.add(_candidate("c2", ReviewStatus.ACCEPTED))
    assert [c.candidate_id for c in queue.list_pending()] == ["c1"]


def test_update_transitions_and_stamps_reviewed_at(tmp_path) -> None:
    queue = ReviewQueue(tmp_path)
    queue.add(_candidate())
    updated = queue.update(
        "c1",
        status=ReviewStatus.ACCEPTED,
        category=ImprovementCategory.KNOWLEDGE_GAP,
        notes="confirmed gap",
        reviewed_by="human",
    )
    assert updated is not None
    assert updated.status is ReviewStatus.ACCEPTED
    assert updated.category is ImprovementCategory.KNOWLEDGE_GAP
    assert updated.notes == "confirmed gap"
    assert updated.reviewed_by == "human"
    assert updated.reviewed_at  # review timestamp recorded


def test_update_preserves_unrelated_fields(tmp_path) -> None:
    queue = ReviewQueue(tmp_path)
    queue.add(_candidate())
    updated = queue.update("c1", status=ReviewStatus.REJECTED)
    assert updated is not None
    assert updated.trace_id == "t1"  # untouched
    assert updated.reviewed_at


def test_update_unknown_id_returns_none(tmp_path) -> None:
    queue = ReviewQueue(tmp_path)
    assert queue.update("nope", status=ReviewStatus.REJECTED) is None


def test_update_is_persisted_across_instances(tmp_path) -> None:
    queue = ReviewQueue(tmp_path)
    queue.add(_candidate())
    queue.update("c1", status=ReviewStatus.NO_ACTION)
    reloaded = ReviewQueue(tmp_path)
    assert reloaded.get("c1").status is ReviewStatus.NO_ACTION


def test_persistence_survives_reload(tmp_path) -> None:
    queue = ReviewQueue(tmp_path)
    queue.add(_candidate(make_id("cand")))
    queue.add(_candidate(make_id("cand")))
    reloaded = ReviewQueue(tmp_path)
    assert len(reloaded.list_all()) == 2
