"""Stage 5 evaluation E2E integration test.

Full pipeline: build agent -> initialize LightRAGAdapter -> ingest ->
evaluate a small labeled subset (direct-answer / factual / terminology /
unknown) -> derive per-dimension verdicts -> aggregate metrics -> close.

Semantic-keypoint assertions only (spec §55); the run itself must neither
crash nor invent sources for the unknown case. Requires provider
credentials (skipped by default).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dev_knowledge_agent.adapters.lightrag.adapter import LightRAGAdapter
from dev_knowledge_agent.adapters.lightrag.native_baseline import (
    env_vars_available,
    ingest_documents,
)
from dev_knowledge_agent.bootstrap import build_agent
from dev_knowledge_agent.config.settings import get_settings
from dev_knowledge_agent.evaluation.evaluator import build_case_result
from dev_knowledge_agent.evaluation.models import EvalCase
from dev_knowledge_agent.evaluation.runner import EvaluationRunner
from dev_knowledge_agent.observability.sinks import InMemoryTraceSink
from dev_knowledge_agent.observability.tracer import Tracer

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KB_FILES = [
    PROJECT_ROOT / "examples" / "knowledge_base" / name
    for name in ("deployment.md", "api_auth.md", "incident_runbook.md", "service_overview.md")
]

#: keep the real run small: one case per behavior class under evaluation.
#: d1 direct answer (no tool) | f1 factual | t1 terminology | u1 unknown.
EVAL_CASES = [
    EvalCase.model_validate_json(line)
    for line in (
        '{"id":"d1","query":"你好","category":"direct_answer","should_call_tool":false}',
        '{"id":"f1","query":"Access token 的有效期是多少？","category":"factual",'
        '"should_call_tool":true,"expected_intent":"factual","expected_strategy":"focused",'
        '"expected_sources":["api_auth.md"],"expected_answer_terms":["30","分钟"]}',
        '{"id":"t1","query":"DB_CONNECTION_POOL_EXHAUSTED 是什么意思？","category":"terminology",'
        '"should_call_tool":true,"expected_intent":"terminology","expected_strategy":"focused",'
        '"expected_sources":["incident_runbook.md"],"expected_answer_terms":["连接池"]}',
        '{"id":"u1","query":"Billing Service 使用什么数据库？","category":"unknown",'
        '"should_call_tool":true,"expected_intent":"general","expect_abstain":true}',
    )
]


def _skip_unless_credentials() -> None:
    if not env_vars_available():
        pytest.skip("Real provider credentials are required (DEEPSEEK_API_KEY)")


def test_evaluation_e2e(tmp_path: Path) -> None:
    """Build -> init -> ingest -> run 4 labeled cases -> aggregate metrics."""
    _skip_unless_credentials()
    workdir = tmp_path / "lightrag_stage5_eval"
    from dev_knowledge_agent.adapters.lightrag.settings import LightRAGAdapterSettings

    settings = LightRAGAdapterSettings(
        working_dir=workdir,
        workspace=f"dka_stage5_{workdir.resolve().name}",
    )
    adapter = LightRAGAdapter(
        working_dir=workdir,
        settings=settings,
        knowledge_roots=[PROJECT_ROOT / "examples"],
    )

    async def scenario() -> object:
        sink = InMemoryTraceSink()
        tracer = Tracer(sinks=[sink])
        built = build_agent(get_settings(), lightrag_adapter=adapter, tracer=tracer)

        async def run_case(case: EvalCase) -> object:  # noqa: ANN401 - eval glue
            sink.clear()
            result = await built.orchestrator.run(case.query)
            return build_case_result(case, result, sink.events)

        try:
            await built.adapter.initialize()
            kernel = built.adapter._kernel  # noqa: SLF001 - test probes kernel
            assert kernel is not None
            await ingest_documents(kernel, KB_FILES)

            runner = EvaluationRunner(run_case=run_case, dataset="test_evaluation_e2e")
            return await runner.run(EVAL_CASES)
        finally:
            await built.adapter.close()

    run_result = asyncio.run(scenario())
    m = run_result.metrics

    by_id = {c.case_id: c for c in run_result.cases}
    assert len(run_result.cases) == 4, [c.case_id for c in run_result.cases]

    #: d1 -- direct answer must NOT call the tool.
    d1 = by_id["d1"]
    assert d1.tool_called is False
    assert d1.status == "SUCCESS"

    #: f1 -- tool used, intent/strategy follow the routing policy, answer
    #: grounded with the 30-minute fact and the api_auth.md citation.
    f1 = by_id["f1"]
    assert f1.tool_called is True
    assert f1.primary_intent is not None and f1.primary_intent.value == "factual"
    assert f1.answer_terms_all_present is True, f1.answer
    assert any("api_auth" in c for c in f1.citations), f1.citations

    #: Stage 5.1 provenance triple (§29): original_user_query, tool_query and
    #: the routing decision coexist on every knowledge-search step.
    assert f1.routing_steps, "knowledge-search cases must surface routing steps"
    for step in f1.routing_steps:
        assert step.original_user_query == f1.query
        assert step.tool_query, "tool_query must be captured"
        assert step.intent is not None
    assert f1.primary_intent is not None

    #: t1 -- terminology routing + incident_runbook.md source.
    t1 = by_id["t1"]
    assert t1.tool_called is True
    assert any("incident_runbook" in s for s in t1.actual_sources), t1.actual_sources

    #: u1 -- unknown knowledge: Agent must not invent a database; it should
    #: either abstain explicitly or admit insufficiency.
    u1 = by_id["u1"]
    assert u1.tool_called is True
    _refuses = (
        any(token in u1.answer for token in ("没有", "无法", "不足", "信息", "未", "未知"))
        or u1.abstained
    )
    assert _refuses, f"must not invent a database: {u1.answer!r}"

    #: aggregate sanity -- every case carries a trace id and token usage.
    assert all(c.trace_id for c in run_result.cases)
    assert all(c.total_tokens for c in run_result.cases)
    assert m.sample_count == 4
    assert m.tool_selection_accuracy == 1.0
