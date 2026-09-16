"""Shared bootstrapping helper for the Stage 5.2 flywheel CLI demos.

Builds a ``DataFlywheelService`` wired to the gitignored ``.local/``
directories (feedback / review / flywheel) so the four flywheel CLIs
(``submit_feedback`` / ``review_feedback`` / ``flywheel_report`` /
``promote_eval_case``) operate on the same single storage root.

Also loads the local ``.env`` secrets (existing env vars win) -- kept
dependency-free like the other demo scripts.
"""

from __future__ import annotations

import os
from pathlib import Path

from polaris_agentic_rag.flywheel.candidate_generator import ReviewCandidateGenerator
from polaris_agentic_rag.flywheel.eval_promotion import EvalCandidateStore
from polaris_agentic_rag.flywheel.models import ImprovementProposal
from polaris_agentic_rag.flywheel.repository import JsonlFeedbackRepository, JsonlStore
from polaris_agentic_rag.flywheel.review_queue import ReviewQueue
from polaris_agentic_rag.flywheel.service import DataFlywheelService
from polaris_agentic_rag.retrieval.router import QueryRouter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FLYWHEEL_ROOT = PROJECT_ROOT / ".local"

__all__ = [
    "PROJECT_ROOT",
    "FLYWHEEL_ROOT",
    "load_env_file",
    "build_flywheel",
]


def load_env_file(env_path: Path) -> None:
    """Load ``KEY=VALUE`` pairs from a local .env file into the environment."""
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_flywheel() -> DataFlywheelService:
    """Compose the flywheel on the gitignored ``.local/`` storage root."""
    return DataFlywheelService(
        feedback_repository=JsonlFeedbackRepository(FLYWHEEL_ROOT / "feedback"),
        review_queue=ReviewQueue(FLYWHEEL_ROOT / "review"),
        generator=ReviewCandidateGenerator(router=QueryRouter()),
        proposal_store=JsonlStore(
            FLYWHEEL_ROOT / "flywheel" / "proposals.jsonl",
            id_field="proposal_id",
            model=ImprovementProposal,
        ),
        eval_candidate_store=EvalCandidateStore(
            FLYWHEEL_ROOT / "flywheel" / "eval_candidates.jsonl"
        ),
    )
