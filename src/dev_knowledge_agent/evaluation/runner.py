"""Evaluation runner (spec §40-42).

``EvaluationRunner`` is framework-agnostic: it receives a ``run_case``
callable (the CLI / integration test wires it to the real composed Agent)
and orchestrates load -> run -> evaluate -> save -> print. It never imports
LightRAG or a provider SDK.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from dev_knowledge_agent.evaluation.metrics import compute_metrics
from dev_knowledge_agent.evaluation.models import EvalCase, EvalCaseResult, EvalRunResult

__all__ = ["EvaluationRunner", "load_dataset", "print_summary", "save_run_result"]

logger = logging.getLogger(__name__)

#: A ``run_case`` executes one EvalCase and returns its full result.
RunCase = Callable[[EvalCase], Awaitable[EvalCaseResult]]


def load_dataset(path: str | Path) -> list[EvalCase]:
    """Load an evaluation dataset from a JSONL file (one EvalCase per line)."""
    cases: list[EvalCase] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            cases.append(EvalCase.model_validate_json(stripped))
    return cases


class EvaluationRunner:
    """Runs a dataset through ``run_case`` and aggregates the metrics."""

    def __init__(
        self,
        *,
        run_case: RunCase,
        dataset: str = "",
    ) -> None:
        self._run_case = run_case
        self._dataset = dataset

    async def run(
        self,
        cases: list[EvalCase],
        *,
        sample_limit: int | None = None,
    ) -> EvalRunResult:
        """Sequentially evaluate ``cases`` (optionally only the first N)."""
        selected = cases if sample_limit is None else cases[:sample_limit]
        results: list[EvalCaseResult] = []
        for i, case in enumerate(selected, start=1):
            try:
                case_result = await self._run_case(case)
            except Exception as exc:  # noqa: BLE001 - keep the run going
                logger.warning("case %s crashed: %s", case.id, exc)
                continue
            results.append(case_result)
            logger.info(
                "[%d/%d] %s -> status=%s tool=%s",
                i,
                len(selected),
                case.id,
                case_result.status,
                case_result.tool_called,
            )
        metrics = compute_metrics(results)
        return EvalRunResult(
            dataset=self._dataset,
            run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            sample_count=len(results),
            cases=results,
            metrics=metrics,
        )


def save_run_result(result: EvalRunResult, directory: str | Path) -> Path:
    """Serialize one run to ``directory/eval-<iso>.json`` (gitignored)."""
    directory_path = Path(directory)
    directory_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = directory_path / f"eval-{stamp}.json"
    out_path.write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def print_summary(result: EvalRunResult) -> None:
    """Print a concise human-readable summary (§42)."""
    m = result.metrics
    print("=" * 60)
    print(f"Evaluation summary  (n={m.sample_count}, dataset={result.dataset})")
    print("=" * 60)
    print(
        f"Tool selection accuracy : {_fmt_rate(m.tool_selection_accuracy)}  "
        f"(precision={_fmt_rate(m.tool_call_precision)}, "
        f"recall={_fmt_rate(m.tool_call_recall)})"
    )
    print(f"  false positives: {m.false_positive_count}  false negatives: {m.false_negative_count}")
    print(f"Routing intent accuracy : {_fmt_rate(m.intent_accuracy)}")
    print(
        f"Routing strategy accuracy: {_fmt_rate(m.strategy_accuracy)}  "
        f"fallback rate: {_fmt_rate(m.fallback_rate)}"
    )
    print(
        f"Expected source recall  : {_fmt_rate(m.expected_source_recall)}  "
        f"no-evidence rate: {_fmt_rate(m.no_evidence_rate)}"
    )
    print(
        f"Citation grounded rate  : {_fmt_rate(m.citation_grounded_rate)}  "
        f"source recall: {_fmt_rate(m.citation_source_recall)}"
    )
    print(f"Answer term match rate  : {_fmt_rate(m.answer_term_match_rate)}")
    print(f"Abstention accuracy     : {_fmt_rate(m.abstention_accuracy)}")
    print(f"Latency p50/p95 (ms)    : {_fmt_ms(m.latency_p50_ms)} / {_fmt_ms(m.latency_p95_ms)}")
    print(
        f"Tokens (in/out/total)   : {m.total_input_tokens} / "
        f"{m.total_output_tokens} / {m.total_tokens}"
    )
    print(f"Failure counts          : {m.failure_counts or '{}'}")
    print(f"Failed cases            : {m.failed_case_ids or '[]'}")
    print("=" * 60)


def _fmt_rate(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def _fmt_ms(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "n/a"
