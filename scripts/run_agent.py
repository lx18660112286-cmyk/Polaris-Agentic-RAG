"""Stage 4 Agent CLI demo (simple REPL).

Runs the composed Agent against the example knowledge base. Requires real
provider credentials in the environment (``DEEPSEEK_API_KEY``).

Usage (from project root, inside .venv):

    .\\.venv\\Scripts\\python.exe scripts/run_agent.py
    .\\.venv\\Scripts\\python.exe scripts/run_agent.py --debug
    .\\.venv\\Scripts\\python.exe scripts/run_agent.py --no-feedback

``--debug`` traces every Agent event and prints the per-query event log
(also archived as JSONL under ``.local/traces/``).

The Stage 5.2 data flywheel is ON by default (runtime feedback): after each
answered query you rate the answer (enter/i/t/n/b/?), the feedback (bound to
the runtime trace) is recorded into ``.local/feedback/``, any matching review
candidates are queued, and a live status line is printed. Use ``/status`` to
view aggregate flywheel metrics, ``/skip`` to skip rating this round, and
``/nofeedback`` to disable rating for the session. Pass ``--no-feedback`` to
disable the flywheel entirely. This is a side channel only -- the flywheel
never changes the agent's behavior.

Type a query; type `exit` / `quit` to stop.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from _flywheel_cli import build_flywheel

from polaris_agentic_rag.adapters.lightrag.native_baseline import ingest_documents
from polaris_agentic_rag.bootstrap import build_agent, create_lightrag_adapter
from polaris_agentic_rag.config.settings import get_settings
from polaris_agentic_rag.flywheel.models import (
    FeedbackType,
    ImprovementCategory,
    ReviewCandidate,
    is_negative_feedback,
)
from polaris_agentic_rag.flywheel.service import DataFlywheelService
from polaris_agentic_rag.observability.sinks import InMemoryTraceSink, JsonlTraceSink
from polaris_agentic_rag.observability.tracer import Tracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKDIR = PROJECT_ROOT / ".local" / "agent_legal_v1"
TRACE_DIR = PROJECT_ROOT / ".local" / "traces"
LEGAL_KB_DIR = PROJECT_ROOT / "examples" / "knowledge_base" / "legal"


def should_index(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith("_"):
        return False
    if name.startswith("coverage_gap"):
        return False
    return path.suffix.lower() == ".md"


KB_FILES = sorted(p for p in LEGAL_KB_DIR.rglob("*.md") if should_index(p))


def _map_feedback(raw: str) -> FeedbackType | None:
    """Map a single-key rating to a FeedbackType; empty/good -> POSITIVE."""
    if not raw:
        return FeedbackType.POSITIVE
    mapping = {
        "i": FeedbackType.INCORRECT,
        "t": FeedbackType.INCOMPLETE,
        "n": FeedbackType.UNSUPPORTED,
        "b": FeedbackType.BAD_CITATION,
        "?": FeedbackType.OTHER,
    }
    return mapping.get(raw)


def _load_env_file(env_path: Path) -> None:
    """Load ``KEY=VALUE`` pairs from a local .env file into the environment.

    Only sets variables that are not already set in ``os.environ`` (existing
    env vars take precedence), so an explicit ``DEEPSEEK_API_KEY`` export is
    never overridden. Kept dependency-free: a minimal KEY=VALUE parser (no
    quoting/expansion) is enough for the secrets this project keeps in .env.
    """
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


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the live Agent REPL.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="trace Agent events and print them after each query.",
    )
    parser.add_argument(
        "--no-feedback",
        action="store_true",
        help="disable the Stage 5.2 data flywheel (runtime feedback is ON by default).",
    )
    args = parser.parse_args()

    #: Load local secrets from the gitignored .env (existing env vars win).
    _load_env_file(PROJECT_ROOT / ".env")

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY not set; cannot run the live Agent.", file=sys.stderr)
        return

    #: the tracer is always wired so --feedback can bind a trace_id; the
    #: on-disk JSONL archive is only enabled under --debug.
    WORKDIR.mkdir(parents=True, exist_ok=True)
    sink = InMemoryTraceSink()
    tracer = Tracer(sinks=[JsonlTraceSink(TRACE_DIR), sink] if args.debug else [sink])
    adapter = create_lightrag_adapter(
        working_dir=WORKDIR,
        knowledge_roots=[LEGAL_KB_DIR],
    )
    built = build_agent(get_settings(), lightrag_adapter=adapter, tracer=tracer)
    #: the flywheel is ON by default (runtime feedback); --no-feedback disables it.
    flywheel: DataFlywheelService | None = build_flywheel() if not args.no_feedback else None
    #: session-level flywheel counters for the live status line.
    fb_count = 0
    neg_count = 0
    gap_count = 0
    queued: list[str] = []
    feedback_on = flywheel is not None
    try:
        await adapter.initialize()
        kernel = adapter._kernel  # noqa: SLF001 - demo probes the composited kernel
        assert kernel is not None

        print("\nUsing legal knowledge base:")
        print("WORKDIR:", WORKDIR)
        print("LEGAL_KB_DIR:", LEGAL_KB_DIR)
        print("KB_FILES:", len(KB_FILES))
        for path in KB_FILES:
            print(" -", path)
        print()

        await ingest_documents(kernel, KB_FILES)

        while True:
            try:
                query = input("User> ").strip()
            except EOFError:
                break
            if query.lower() in ("exit", "quit"):
                break
            if not query:
                continue
            sink.clear()
            result = await built.orchestrator.run(query)
            print(f"Agent> {result.answer}\n")
            if result.citations:
                print("       sources: " + " ".join(f"[{c}]" for c in result.citations))
            if result.tool_calls:
                print(
                    "       tools: "
                    + ", ".join(f"{t.name}->{t.result_status or 'ok'}" for t in result.tool_calls)
                )
            if result.error:
                print(f"       note: {result.error}")
            if args.debug and sink.events:
                print("       trace:")
                for event in sink.events:
                    attrs = ", ".join(f"{k}={v}" for k, v in event.attributes.items())
                    print(
                        f"         [{event.seq:>2}] {event.event_type.value}"
                        + (f"  ({attrs})" if attrs else "")
                    )
            if flywheel is not None and feedback_on:
                #: runtime flywheel: rate the answer + live commands.
                try:
                    raw = (
                        input(
                            "  rate? [enter=good / i=incorrect / t=brief / n=no evidence / "
                            "b=bad cite / ?=other / /status / /skip / /nofeedback] > "
                        )
                        .strip()
                        .lower()
                    )
                except EOFError:
                    break
                if raw.startswith("/"):
                    if raw == "/status":
                        print(flywheel.report())
                    elif raw == "/nofeedback":
                        feedback_on = False
                        print("       flywheel scoring disabled for this session.")
                    elif raw == "/skip":
                        pass  # don't record this round
                    else:
                        print("       unknown command; try /status /skip /nofeedback")
                    continue
                feedback_type = _map_feedback(raw)
                if feedback_type is None:
                    print(
                        "       unknown rating; use enter/i/t/n/b/? (or /status /skip /nofeedback)"
                    )
                    continue
                trace_id = result.trace_id or ""
                feedback_event = await flywheel.capture_feedback(
                    trace_id=trace_id,
                    query=query,
                    answer=result.answer,
                    feedback_type=feedback_type,
                )
                fb_count += 1
                print(
                    f"       feedback recorded: {feedback_event.feedback_id}"
                    f" ({feedback_type.value})"
                )
                if is_negative_feedback(feedback_type):
                    neg_count += 1
                    candidates: list[ReviewCandidate] = flywheel.create_candidates(
                        result, feedback=feedback_event
                    )
                    for cand in candidates:
                        queued.append(cand.candidate_id)
                        if cand.category is ImprovementCategory.KNOWLEDGE_GAP:
                            gap_count += 1
                    if candidates:
                        print(
                            "       queued for review: "
                            + ", ".join(c.candidate_id for c in candidates)
                        )
                #: live status line so the flywheel is visible at runtime.
                print(
                    f"       [flywheel] feedback={fb_count} negative={neg_count} "
                    f"KNOWLEDGE_GAP={gap_count} queued={len(queued)}"
                )
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
