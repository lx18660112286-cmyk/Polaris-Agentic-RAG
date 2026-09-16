"""Stage 4 Agent CLI demo (simple REPL).

Runs the composed Agent against the example knowledge base. Requires real
provider credentials in the environment (``DEEPSEEK_API_KEY``).

Usage (from project root, inside .venv):

    .\\.venv\\Scripts\\python.exe scripts/run_agent.py
    .\\.venv\\Scripts\\python.exe scripts/run_agent.py --debug
    .\\.venv\\Scripts\\python.exe scripts/run_agent.py --feedback

``--debug`` traces every Agent event and prints the per-query event log
(also archived as JSONL under ``.local/traces/``).

``--feedback`` additionally wires the Stage 5.2 data flywheel (demo): each
answered query asks whether the answer was helpful, records the feedback
(bound to the runtime trace) into ``.local/feedback/``, and queues any
matching review candidates. This is a side channel only -- the flywheel
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
from polaris_agentic_rag.bootstrap import build_agent
from polaris_agentic_rag.config.settings import get_settings
from polaris_agentic_rag.flywheel.models import FeedbackType, is_negative_feedback
from polaris_agentic_rag.observability.sinks import InMemoryTraceSink, JsonlTraceSink
from polaris_agentic_rag.observability.tracer import Tracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKDIR = PROJECT_ROOT / ".local" / "agent_live"
TRACE_DIR = PROJECT_ROOT / ".local" / "traces"
KB_FILES = [
    PROJECT_ROOT / "examples" / "knowledge_base" / name
    for name in ("deployment.md", "api_auth.md", "incident_runbook.md", "service_overview.md")
]


def _collect_feedback() -> FeedbackType | None:
    """Ask the user how the last answer was; return a type or None to skip."""
    print(
        "    was the answer helpful?  [enter=praise/good / i=incorrect / t=too brief / ?=other] > ",
        end="",
    )
    try:
        raw = input().strip().lower()
    except EOFError:
        return None
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
        "--feedback",
        action="store_true",
        help="enable the Stage 5.2 data flywheel demo (record per-query feedback).",
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
    built = build_agent(get_settings(), working_dir=WORKDIR, tracer=tracer)
    adapter = built.adapter
    flywheel = build_flywheel() if args.feedback else None
    try:
        await adapter.initialize()
        kernel = adapter._kernel  # noqa: SLF001 - demo probes the composited kernel
        assert kernel is not None
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
            if flywheel is not None:
                feedback_type = _collect_feedback()
                if feedback_type is not None:
                    trace_id = result.trace_id or ""
                    feedback_event = await flywheel.capture_feedback(
                        trace_id=trace_id,
                        query=query,
                        answer=result.answer,
                        feedback_type=feedback_type,
                    )
                    print(
                        f"       feedback recorded: {feedback_event.feedback_id}"
                        f" ({feedback_type.value})"
                    )
                    if is_negative_feedback(feedback_type):
                        candidates = flywheel.create_candidates(result, feedback=feedback_event)
                        if candidates:
                            print(
                                "       queued for review: "
                                + ", ".join(c.candidate_id for c in candidates)
                            )
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
