"""Stage 5 evaluation CLI (spec §40-42).

Runs the composed Agent against the labeled evaluation dataset
(``examples/evaluation/dev_knowledge_eval.jsonl``), captures one trace per
case, derives per-dimension verdicts, aggregates the metrics and saves the
full run result (cases + metrics) to ``.local/eval/`` (gitignored).

Usage (from project root, inside .venv):

    .\\.venv\\Scripts\\python.exe scripts/run_evaluation.py
    .\\.venv\\Scripts\\python.exe scripts/run_evaluation.py --limit 5
    .\\.venv\\Scripts\\python.exe scripts/run_evaluation.py --dataset <path>
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from polaris_agentic_rag.adapters.lightrag.native_baseline import ingest_documents
from polaris_agentic_rag.bootstrap import build_agent
from polaris_agentic_rag.config.settings import get_settings
from polaris_agentic_rag.evaluation.evaluator import build_case_result
from polaris_agentic_rag.evaluation.models import EvalCase, EvalCaseResult
from polaris_agentic_rag.evaluation.runner import (
    EvaluationRunner,
    load_dataset,
    print_summary,
    save_run_result,
)
from polaris_agentic_rag.observability.sinks import InMemoryTraceSink, JsonlTraceSink
from polaris_agentic_rag.observability.tracer import Tracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKDIR = PROJECT_ROOT / ".local" / "eval_live"
TRACE_DIR = PROJECT_ROOT / ".local" / "traces"
OUTPUT_DIR = PROJECT_ROOT / ".local" / "eval"
DEFAULT_DATASET = PROJECT_ROOT / "examples" / "evaluation" / "dev_knowledge_eval.jsonl"
KB_FILES = [
    PROJECT_ROOT / "examples" / "knowledge_base" / name
    for name in ("deployment.md", "api_auth.md", "incident_runbook.md", "service_overview.md")
]


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Stage 5 evaluation.")
    parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N cases.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to the JSONL evaluation dataset.",
    )
    args = parser.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY not set; cannot run the live evaluation.", file=sys.stderr)
        return 2

    print(f"dataset     : {args.dataset}")
    print(f"sample limit: {args.limit or 'all'}")
    print(f"trace dir   : {TRACE_DIR}")

    cases = load_dataset(args.dataset)
    print(f"loaded cases: {len(cases)}")

    #: one shared Tracer -> per-case in-memory buffer (fresh after clear)
    #: + on-disk JSONL archive (one file per trace_id, gitignored).
    sink = InMemoryTraceSink()
    tracer = Tracer(sinks=[JsonlTraceSink(TRACE_DIR), sink])

    WORKDIR.mkdir(parents=True, exist_ok=True)
    built = build_agent(
        get_settings(),
        working_dir=WORKDIR,
        tracer=tracer,
    )
    adapter = built.adapter

    async def run_case(case: EvalCase) -> EvalCaseResult:
        sink.clear()
        result = await built.orchestrator.run(case.query)
        return build_case_result(case, result, sink.events)

    runner = EvaluationRunner(
        run_case=run_case,
        dataset=str(args.dataset),
        #: Layer B: route the ORIGINAL queries through the same Router the
        #: tool uses, bypassing the Agent rewrite chain (spec §3).
        router=built.rag_tool.router,
    )

    try:
        await adapter.initialize()
        kernel = adapter._kernel  # noqa: SLF001 - demo probes the composited kernel
        assert kernel is not None
        await ingest_documents(kernel, KB_FILES)

        result = await runner.run(cases, sample_limit=args.limit)
    finally:
        await adapter.close()

    print_summary(result)
    out_path = save_run_result(result, OUTPUT_DIR)
    print(f"saved run result -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
