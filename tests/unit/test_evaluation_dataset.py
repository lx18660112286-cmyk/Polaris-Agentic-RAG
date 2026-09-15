"""Offline tests for dataset loading + basic sanity checks (spec §4/§6/§7)."""

from __future__ import annotations

from pathlib import Path

from polaris_agentic_rag.evaluation.runner import load_dataset
from polaris_agentic_rag.retrieval.models import RetrievalIntent, RetrievalStrategy

DATASET = (
    Path(__file__).resolve().parents[2] / "examples" / "evaluation" / "dev_knowledge_eval.jsonl"
)


def test_dataset_file_exists() -> None:
    assert DATASET.is_file(), f"dataset missing at {DATASET}"


def test_dataset_loads_and_has_20_to_40_cases() -> None:
    cases = load_dataset(DATASET)
    assert 20 <= len(cases) <= 40, f"expected 20-40 cases, got {len(cases)}"
    assert len({c.id for c in cases}) == len(cases), "case ids must be unique"


def test_dataset_covers_required_categories() -> None:
    cases = load_dataset(DATASET)
    categories = {c.category for c in cases}
    required = {
        "direct_answer",
        "factual",
        "terminology",
        "relationship",
        "multi_document",
        "overview",
        "unknown",
        "insufficient_evidence",
        "generic",
    }
    assert required.issubset(categories), f"missing categories: {required - categories}"


def test_dataset_cases_have_valid_labels() -> None:
    cases = load_dataset(DATASET)
    for case in cases:
        assert case.query.strip(), f"case {case.id} has empty query"
        assert case.category, f"case {case.id} has empty category"

        if case.expect_abstain:
            assert case.should_call_tool, f"abstention case {case.id} must consult the tool"

        #: expected strategy must be consistent with intent policy when both set
        if case.expected_intent is not None and case.expected_strategy is not None:
            if case.expected_intent is RetrievalIntent.FACTUAL:
                assert case.expected_strategy is RetrievalStrategy.FOCUSED
            if case.expected_intent is RetrievalIntent.OVERVIEW:
                assert case.expected_strategy is RetrievalStrategy.GLOBAL
            if case.expected_intent is RetrievalIntent.RELATIONAL:
                assert case.expected_strategy is RetrievalStrategy.HYBRID
            if case.expected_intent is RetrievalIntent.MULTI_DOCUMENT:
                assert case.expected_strategy is RetrievalStrategy.HYBRID
            if case.expected_intent is RetrievalIntent.GENERAL:
                assert case.expected_strategy is RetrievalStrategy.HYBRID


def test_dataset_intent_is_app_contract_not_query_param() -> None:
    cases = load_dataset(DATASET)
    serialized = cases[0].model_dump()
    assert "QueryParam" not in str(serialized)
    assert "top_k" not in serialized
    assert "mode" not in serialized


def test_dataset_has_both_tool_and_direct_answer_cases() -> None:
    cases = load_dataset(DATASET)
    should_call = [c for c in cases if c.should_call_tool]
    direct = [c for c in cases if not c.should_call_tool]
    assert len(should_call) >= 10
    assert len(direct) >= 4


def test_dataset_spans_all_factual_and_terminology_examples() -> None:
    cases = load_dataset(DATASET)
    queries = {c.query for c in cases}
    #: spec §6B/§6C examples must be present (labels may vary per project baseline)
    assert "Access token 的有效期是多少？" in queries
    assert "DB_CONNECTION_POOL_EXHAUSTED 是什么意思？" in queries
