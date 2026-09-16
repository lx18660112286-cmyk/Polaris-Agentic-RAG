"""Data Flywheel (Stage 5.2) -- human-reviewed, auditable improvement loop.

Turns real runtime queries / traces / feedback / failures into explicit
review candidates, improvement proposals and regression-gated eval cases --
without ever auto-modifying the prompt, the router, or the knowledge base
(spec §2/§28/§35). The flywheel runs as a *bypass*: runtime path ≠
learning path (spec §3/§68).
"""

from __future__ import annotations

from polaris_agentic_rag.flywheel.models import (
    EvalCandidate,
    FeedbackEvent,
    FeedbackType,
    FlywheelMetrics,
    ImprovementCategory,
    ImprovementProposal,
    ProposalType,
    RegressionCheckResult,
    ReviewCandidate,
    ReviewPriority,
    ReviewSource,
    ReviewStatus,
)
from polaris_agentic_rag.flywheel.service import DataFlywheelService

__all__ = [
    "DataFlywheelService",
    "EvalCandidate",
    "FeedbackEvent",
    "FeedbackType",
    "FlywheelMetrics",
    "ImprovementCategory",
    "ImprovementProposal",
    "ProposalType",
    "RegressionCheckResult",
    "ReviewCandidate",
    "ReviewPriority",
    "ReviewSource",
    "ReviewStatus",
]
