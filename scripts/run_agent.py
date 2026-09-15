"""Stage 4 Agent CLI demo (simple REPL).

Runs the composed Agent against the example knowledge base. Requires real
provider credentials in the environment (``DEEPSEEK_API_KEY``).

Usage (from project root, inside .venv):

    .\\.venv\\Scripts\\python.exe scripts/run_agent.py
    .\\.venv\\Scripts\\python.exe scripts/run_agent.py --debug

``--debug`` traces every Agent event and prints the per-query event log
(also archived as JSONL under ``.local/traces/``).

Type a query; type `exit` / `quit` to stop.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dev_knowledge_agent.adapters.lightrag.native_baseline import ingest_documents
from dev_knowledge_agent.bootstrap import build_agent
from dev_knowledge_agent.config.settings import get_settings
from dev_knowledge_agent.observability.sinks import InMemoryTraceSink, JsonlTraceSink
from dev_knowledge_agent.observability.tracer import Tracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKDIR = PROJECT_ROOT / ".local" / "agent_live"
TRACE_DIR = PROJECT_ROOT / ".local" / "traces"
KB_FILES = [
    PROJECT_ROOT / "examples" / "knowledge_base" / name
    for name in ("deployment.md", "api_auth.md", "incident_runbook.md", "service_overview.md")
]


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
    args = parser.parse_args()

    #: Load local secrets from the gitignored .env (existing env vars win).
    _load_env_file(PROJECT_ROOT / ".env")

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY not set; cannot run the live Agent.", file=sys.stderr)
        return

    #: verify the example KB is ingested once for this CLI session.
    WORKDIR.mkdir(parents=True, exist_ok=True)
    sink = InMemoryTraceSink()
    tracer = Tracer(sinks=[JsonlTraceSink(TRACE_DIR), sink]) if args.debug else None
    built = build_agent(get_settings(), working_dir=WORKDIR, tracer=tracer)
    adapter = built.adapter
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
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
