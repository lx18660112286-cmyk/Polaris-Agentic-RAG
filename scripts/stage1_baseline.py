"""Stage 1 baseline runner (reproducible).

Runs the full native LightRAG E2E baseline over the example knowledge
base and dumps structured observations to a JSON file under the local
runtime directory (gitignored). No secrets are printed.

Usage (from project root, inside .venv):

    .\\.venv\\Scripts\\python.exe scripts/stage1_baseline.py

The runner only imports the adapter harness, never LightRAG directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dev_knowledge_agent.adapters.lightrag.native_baseline import (
    QUERY_MODES,
    build_lightrag,
    env_vars_available,
    ingest_documents,
    run_query,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_FILES = [
    PROJECT_ROOT / "examples" / "knowledge_base" / name
    for name in ("deployment.md", "api_auth.md", "incident_runbook.md", "service_overview.md")
]
WORKDIR = PROJECT_ROOT / ".local" / "lightrag_stage1"
OUTPUT = WORKDIR / "baseline_results.json"
FIXTURES = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "stage1_queries.json").read_text(encoding="utf-8")
)


async def main() -> int:
    if not env_vars_available():
        print("BLOCKED_BY_CREDENTIALS: DEEPSEEK_API_KEY is missing from the environment.")
        return 2

    WORKDIR.mkdir(parents=True, exist_ok=True)
    rag = build_lightrag(WORKDIR)
    report: dict[str, object] = {
        "pinned_lightrag_commit": "02dcd8df754ec312b807bdd4d67737b97bc38679",
        "llm_provider": "deepseek (openai_compatible)",
        "llm_model": os.environ.get("DKA_LIGHTRAG_LLM_MODEL", "deepseek-chat"),
        "embedding_provider": "ollama",
        "embedding_model": getattr(rag.embedding_func, "model_name", "bge-m3:latest"),
        "rerank": "not configured",
        "working_dir": str(WORKDIR),
    }

    try:
        t0 = time.perf_counter()
        await rag.initialize_storages()
        report["initialize_storages_s"] = round(time.perf_counter() - t0, 2)

        start = time.perf_counter()
        await ingest_documents(rag, KB_FILES)
        report["ingest_duration_s"] = round(time.perf_counter() - start, 2)
        report["ingested_documents"] = len(KB_FILES)

        #: Case A-H on a representative mode (hybrid)
        case_observations = []
        for case in FIXTURES["cases"]:
            obs = await run_query(rag, str(case["query"]), mode="hybrid")
            obs.case_id = str(case["case_id"])
            case_observations.append(vars(obs))
        report["cases_hybrid"] = case_observations

        #: Query mode comparison across a representative subset
        mode_observations = []
        for query in FIXTURES["mode_compare_queries"]:
            for mode in QUERY_MODES:
                obs = await run_query(rag, str(query), mode=mode)
                obs.case_id = query[:24]
                mode_observations.append(vars(obs))
        report["mode_comparison"] = mode_observations

        #: Rerank comparison (only meaningful if a rerank provider is configured)
        rerank_observations = []
        if False:  # pragma: no cover - future rerank provider
            for query in FIXTURES["rerank_compare_queries"]:
                off = await run_query(rag, str(query), mode="hybrid", enable_rerank=False)
                on = await run_query(rag, str(query), mode="hybrid", enable_rerank=True)
                rerank_observations.append(
                    {"query": str(query), "rerank_off": vars(off), "rerank_on": vars(on)}
                )
        report["rerank_comparison"] = rerank_observations
        report["rerank_note"] = (
            "Rerank baseline not executed: no rerank provider is configured in .env "
            "(LightRAG warning behavior left as-is)."
        )

        #: Failure probes (no side effects / no cost)
        failure_probes: dict[str, object] = {}
        empty_obs = await run_query(rag, "", mode="hybrid")
        failure_probes["empty_query"] = {
            "error": empty_obs.error,
            "data_status": empty_obs.data_status,
        }

        invalid_mode_obs = await run_query(rag, "Access token 的有效期是多少？", mode="not_a_mode")
        failure_probes["invalid_query_mode"] = {
            "error": invalid_mode_obs.error,
            "data_status": invalid_mode_obs.data_status,
        }
        report["failure_probes"] = failure_probes

        uninit_rag = build_lightrag(PROJECT_ROOT / ".local" / "never_initialized_tmp")
        try:
            uninit_obs = await run_query(uninit_rag, "Access token 的有效期是多少？", mode="hybrid")
            failure_probes["query_before_initialize"] = {"error": uninit_obs.error}
        finally:
            await uninit_rag.finalize_storages()
    except Exception as exc:  # noqa: BLE001 - report kernel failure shape
        report["lifecycle_error"] = f"{type(exc).__name__}: {exc}"
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1
    finally:
        await rag.finalize_storages()

    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"baseline results written to {OUTPUT}")
    return 0


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None  # type: ignore[assignment]
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env")
    sys.exit(asyncio.run(main()))
