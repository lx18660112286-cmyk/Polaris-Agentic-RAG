"""Stage 4 Agent CLI demo (simple REPL).

Runs the composed Agent against the example knowledge base. Requires real
provider credentials in the environment (``DEEPSEEK_API_KEY``).

Usage (from project root, inside .venv):

    .\\.venv\\Scripts\\python.exe scripts/run_agent.py

Type a query; type `exit` / `quit` to stop.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dev_knowledge_agent.adapters.lightrag.native_baseline import ingest_documents
from dev_knowledge_agent.bootstrap import build_agent
from dev_knowledge_agent.config.settings import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKDIR = PROJECT_ROOT / ".local" / "agent_live"
KB_FILES = [
    PROJECT_ROOT / "examples" / "knowledge_base" / name
    for name in ("deployment.md", "api_auth.md", "incident_runbook.md", "service_overview.md")
]


async def main() -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY not set; cannot run the live Agent.", file=sys.stderr)
        return

    #: verify the example KB is ingested once for this CLI session.
    WORKDIR.mkdir(parents=True, exist_ok=True)
    built = build_agent(get_settings(), working_dir=WORKDIR)
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
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
