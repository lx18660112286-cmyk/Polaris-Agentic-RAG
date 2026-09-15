"""Evaluation module (Stage 5).

Structured evaluation over the composed Agent: per-case ``EvalCase``
labeling (tool selection, routing expectation, expected sources / key
terms, abstention) transformed into per-dimension verdicts
(``evaluation/metrics.py``) and aggregated into a reproducible
``EvalRunResult`` JSON (``evaluation/runner.py``).

``evaluation/`` never imports LightRAG or a provider SDK (architecture
guard): actuals arrive through ``AgentResult`` + captured ``TraceEvent``s,
and the real execution is owned by the caller (CLI / integration test).
"""

from __future__ import annotations

from polaris_agentic_rag.evaluation.evaluator import build_case_result
from polaris_agentic_rag.evaluation.metrics import (
    ConfusionCounts,
    compute_metrics,
)
from polaris_agentic_rag.evaluation.models import (
    EvalCase,
    EvalCaseResult,
    EvalRunResult,
    MetricSummary,
)
from polaris_agentic_rag.evaluation.runner import (
    EvaluationRunner,
    load_dataset,
    print_summary,
    save_run_result,
)

__all__ = [
    "ConfusionCounts",
    "EvalCase",
    "EvalCaseResult",
    "EvalRunResult",
    "EvaluationRunner",
    "MetricSummary",
    "build_case_result",
    "compute_metrics",
    "load_dataset",
    "print_summary",
    "save_run_result",
]
