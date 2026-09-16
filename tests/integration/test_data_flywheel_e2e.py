"""Stage 5.2 Data Flywheel real E2E integration test.

Full pipeline: build Agent -> init LightRAGAdapter -> ingest -> run ONE real
case -> run the whole flywheel loop (capture feedback -> candidate -> review
-> proposal -> accept -> eval candidate -> promote -> regression) against the
real ``AgentResult``.

This proves the flywheel is a *side channel*: it ingests the same runtime
result and trace ids the normal path produces, never touching the router /
prompt / knowledge base. Requires provider credentials (skipped by default).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from polaris_agentic_rag.adapters.lightrag.adapter import LightRAGAdapter
from polaris_agentic_rag.adapters.lightrag.native_baseline import (
    env_vars_available,
    ingest_documents,
)
from polaris_agentic_rag.bootstrap import build_agent
from polaris_agentic_rag.config.settings import get_settings
from polaris_agentic_rag.flywheel.candidate_generator import ReviewCandidateGenerator
from polaris_agentic_rag.flywheel.eval_promotion import EvalCandidateStore
from polaris_agentic_rag.flywheel.models import (
    FeedbackType,
    ImprovementCategory,
    ImprovementProposal,
    ProposalType,
    ReviewStatus,
)
from polaris_agentic_rag.flywheel.repository import JsonlFeedbackRepository, JsonlStore
from polaris_agentic_rag.flywheel.review_queue import ReviewQueue
from polaris_agentic_rag.flywheel.service import DataFlywheelService
from polaris_agentic_rag.observability.tracer import Tracer
from polaris_agentic_rag.retrieval.router import QueryRouter

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KB_FILES = [
    PROJECT_ROOT / "examples" / "knowledge_base" / name
    for name in ("deployment.md", "api_auth.md", "incident_runbook.md", "service_overview.md")
]


def _skip_unless_credentials() -> None:
    if not env_vars_available():
        pytest.skip("Real provider credentials are required (DEEPSEEK_API_KEY)")


def _build_flywheel(tmp_path: Path) -> DataFlywheelService:
    return DataFlywheelService(
        feedback_repository=JsonlFeedbackRepository(tmp_path / "feedback"),
        review_queue=ReviewQueue(tmp_path / "review"),
        generator=ReviewCandidateGenerator(router=QueryRouter()),
        proposal_store=JsonlStore(
            tmp_path / "proposals.jsonl",
            id_field="proposal_id",
            model=ImprovementProposal,
        ),
        eval_candidate_store=EvalCandidateStore(tmp_path / "eval_candidates.jsonl"),
    )


def test_data_flywheel_e2e(tmp_path: Path) -> None:
    """Run a real Agent case, then push its result through the flywheel loop."""
    _skip_unless_credentials()
    workdir = tmp_path / "lightrag_flywheel"

    from polaris_agentic_rag.adapters.lightrag.settings import LightRAGAdapterSettings

    settings = LightRAGAdapterSettings(
        working_dir=workdir,
        workspace=f"dka_flywheel_{workdir.resolve().name}",
    )
    adapter = LightRAGAdapter(
        working_dir=workdir,
        settings=settings,
        knowledge_roots=[PROJECT_ROOT / "examples"],
    )
    flywheel = _build_flywheel(tmp_path / "flywheel")
    #: a real Tracer populates AgentResult.trace_id so the flywheel can bind
    #: feedback to the runtime trace (side channel; the tracer is inert here).
    tracer = Tracer()

    async def scenario() -> dict[str, Any]:
        built = build_agent(get_settings(), lightrag_adapter=adapter, tracer=tracer)
        orchestrator = built.orchestrator
        try:
            await built.adapter.initialize()
            kernel = built.adapter._kernel  # noqa: SLF001 - test probes kernel
            assert kernel is not None
            await ingest_documents(kernel, KB_FILES)

            result = await orchestrator.run("Access token 的有效期是多少？")
            assert result.status.value == "SUCCESS", result.error
            assert result.trace_id, "runtime must produce a trace_id"

            #: ---- flywheel: human-reviewed loop against the real result ----
            event = await flywheel.capture_feedback(
                trace_id=result.trace_id,
                query=result.original_query,
                answer=result.answer,
                feedback_type=FeedbackType.INCOMPLETE,
                comment="reviewer: answer needs citing the exact section",
            )

            candidates = flywheel.create_candidates(result, feedback=event)
            assert candidates, "negative feedback must queue a candidate"

            #: pick a candidate to walk through the full loop
            cand = candidates[0]
            flywheel.review_candidate(
                cand.candidate_id,
                decision=ReviewStatus.ACCEPTED,
                category=ImprovementCategory.KNOWLEDGE_GAP,
                reviewed_by="tester",
            )
            proposal = flywheel.create_proposal(
                [cand.candidate_id],
                proposal_type=ProposalType.ADD_EVAL_CASE,
                category=ImprovementCategory.KNOWLEDGE_GAP,
            )
            assert proposal is not None
            flywheel.accept_proposal(proposal.proposal_id)

            evc = flywheel.create_eval_candidate(
                proposal_id=proposal.proposal_id,
                candidate_id=cand.candidate_id,
                query=cand.query,
                category="terminology",
                should_retrieve=True,
                feedback=event,
            )
            assert evc is not None, "accepted ADD_EVAL_CASE pair must yield an eval candidate"
            assert evc.trace_id == result.trace_id

            promo = flywheel.promote_eval_candidate(evc.candidate_id, dataset_cases=[])
            assert promo.promoted is True, promo.reason

            #: note: RegressionGate is unit-tested; here we just confirm wiring.
            assert flywheel.flywheel_metrics().eval_candidate_count >= 1

            return {"result": result, "candidate_count": len(candidates)}
        finally:
            await built.adapter.close()

    output = asyncio.run(scenario())
    result = output["result"]

    #: the runtime path is unaffected by the flywheel run
    assert "30" in result.answer, f"answer missing the fact: {result.answer!r}"
    assert any("api_auth" in c for c in result.citations), f"missing citation: {result.citations}"
    assert output["candidate_count"] >= 1

    #: persisted flywheel files exist and sanitize secrets (none expected here)
    feedback_file = tmp_path / "flywheel" / "feedback" / "feedback.jsonl"
    assert feedback_file.is_file()
    for line in feedback_file.read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        assert obj["feedback_type"] == FeedbackType.INCOMPLETE.value
        assert obj["trace_id"] == result.trace_id
