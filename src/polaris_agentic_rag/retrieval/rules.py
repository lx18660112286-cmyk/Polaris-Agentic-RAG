"""Deterministic routing rules (Stage 3).

Stage 3 deliberately uses a *small, deterministic, explainable, cheap,
offline-testable* rule set -- NO LLM classifier. The precedence here is
grounded in Stage 1's real observations:

* local   -> entity-focused / precise facts  -> FOCUSED
* global  -> relationship / overview          -> GLOBAL
* hybrid  -> entity + relationship rich       -> HYBRID
* naive   -> vector-only                      -> VECTOR
* mix     -> graph + vector                   -> MIXED

The pipeline is:

    QueryFeatures --apply--> RetrievalIntent --map--> RetrievalStrategy

Keeping the extraction separate from the mapping keeps the rule set
readable (no "keyword soup") and unit-testable in isolation.
"""

from __future__ import annotations

import re

from polaris_agentic_rag.retrieval.models import (
    RetrievalIntent,
    RetrievalPlan,
    RetrievalStrategy,
)

__all__ = [
    "QueryFeatures",
    "extract_features",
    "decide_intent",
    "INTENT_TO_STRATEGY",
    "default_plan_for_intent",
]

#: Overview language -> whole-system / architecture questions. Checked first
#: because such queries can also contain relationship / factual cues.
_OVERVIEW_MARKERS = (
    "整个系统",
    "如何工作",
    "原理",
    "架构",
    "体系",
    "总体",
    "概览",
    "有哪些主要模块",
    "核心组件",
    "组件和关系",
    "主要由",
    "组成",
)

#: Relationship language -> dependency / relation questions.
_RELATIONSHIP_MARKERS = (
    "依赖",
    "有什么关系",
    "关系",
    "如何关联",
    "连接",
    "上下游",
    "关联",
    "间的关系",
)

#: Definition language used with a technical term.
_DEFINITION_ASKS = (
    "是什么意思",
    "什么意思",
    "什么含义",
    "含义",
    "是做什么",
    "指什么",
    "是什么",
)

#: Operational / incident language -> multi-document troubleshooting.
_OPERATIONAL_MARKERS = (
    "如何定位",
    "如何处理",
    "如何排查",
    "排查",
    "解决",
    "步骤",
    "诊断",
    "回滚",
    "故障",
    "异常",
    "报错",
    "导致",
    "定位问题",
)

#: Explicit factual / value cues (short, grounded in KB-style questions).
#: Note: these are intentionally NOT generic like "什么"; they target value,
#: difference, or time questions so an unclear query falls through to GENERAL.
_FACTUAL_CUES = (
    "是多少",
    "有效期",
    "有什么区别",
    "什么时候",
    "几种",
    "如何计算",
    "怎么算",
    "哪个",
)

#: A technical token: uppercase identifier that reads like a constant / error
#: code (e.g. ``DB_CONNECTION_POOL_EXHAUSTED``, ``REQUEST_TIMEOUT``).
_TECHNICAL_TOKEN = re.compile(r"(?<!\w)[A-Z][A-Z0-9_]{2,}(?!\w)")


class QueryFeatures:
    """Finite, explainable signal set extracted from the raw query."""

    __slots__ = (
        "length",
        "has_overview_marker",
        "has_relationship_marker",
        "has_definition_ask",
        "has_operational_marker",
        "has_factual_cue",
        "has_technical_token",
    )

    length: int
    has_overview_marker: bool
    has_relationship_marker: bool
    has_definition_ask: bool
    has_operational_marker: bool
    has_factual_cue: bool
    has_technical_token: bool

    def __init__(self, query: str) -> None:
        self.length = len(query.strip())
        self.has_overview_marker = any(m in query for m in _OVERVIEW_MARKERS)
        self.has_relationship_marker = any(m in query for m in _RELATIONSHIP_MARKERS)
        self.has_definition_ask = any(m in query for m in _DEFINITION_ASKS)
        self.has_operational_marker = any(m in query for m in _OPERATIONAL_MARKERS)
        self.has_factual_cue = any(m in query for m in _FACTUAL_CUES)
        self.has_technical_token = bool(_TECHNICAL_TOKEN.search(query))


def extract_features(query: str) -> QueryFeatures:
    """Extract a bounded, explainable feature set from a query."""
    return QueryFeatures((query or "").strip())


def decide_intent(features: QueryFeatures, query: str) -> RetrievalIntent:
    """Pick the retrieval intent for the extracted features (deterministic).

    Precedence, most specific first: OVERVIEW > TERMINOLOGY > RELATIONAL >
    MULTI_DOCUMENT > FACTUAL > GENERAL (fallback). Keeping the exact query
    makes the trace readable for people debugging a routing decision.
    """
    del query  #: kept for a clearer trace; not currently used by the rules

    if features.has_overview_marker:
        return RetrievalIntent.OVERVIEW
    #: A technical token + a definition ask -> terminology.
    if features.has_technical_token and features.has_definition_ask:
        return RetrievalIntent.TERMINOLOGY
    #: A definition is explicitly asked -> terminology.
    if features.has_definition_ask:
        return RetrievalIntent.TERMINOLOGY
    #: Relationship language -> relational.
    if features.has_relationship_marker:
        return RetrievalIntent.RELATIONAL
    #: Operational / incident language spanning actions -> multi-document.
    if features.has_operational_marker:
        return RetrievalIntent.MULTI_DOCUMENT
    #: Explicit value / fact cue -> factual.
    if features.has_factual_cue:
        return RetrievalIntent.FACTUAL
    return RetrievalIntent.GENERAL


#: Application strategy for each intent (Stage 1-grounded; ADR 0003).
INTENT_TO_STRATEGY: dict[RetrievalIntent, RetrievalStrategy] = {
    RetrievalIntent.FACTUAL: RetrievalStrategy.FOCUSED,
    RetrievalIntent.TERMINOLOGY: RetrievalStrategy.FOCUSED,
    RetrievalIntent.RELATIONAL: RetrievalStrategy.HYBRID,
    RetrievalIntent.MULTI_DOCUMENT: RetrievalStrategy.HYBRID,
    RetrievalIntent.OVERVIEW: RetrievalStrategy.GLOBAL,
    RetrievalIntent.GENERAL: RetrievalStrategy.HYBRID,
}

_INTENT_REASONS: dict[RetrievalIntent, str] = {
    RetrievalIntent.FACTUAL: "precise factual / value query -> focused entity-level retrieval",
    RetrievalIntent.TERMINOLOGY: "exact term definition -> focused entity-level retrieval",
    RetrievalIntent.RELATIONAL: "asks about dependencies/relations -> hybrid graph+chunk retrieval",
    RetrievalIntent.MULTI_DOCUMENT: (
        "operational multi-step task -> hybrid cross-document retrieval"
    ),
    RetrievalIntent.OVERVIEW: "whole-system/architecture question -> global overview retrieval",
    RetrievalIntent.GENERAL: "unclear intent -> safe hybrid fallback",
}


def default_plan_for_intent(
    intent: RetrievalIntent,
    *,
    top_k: int = 20,
    enable_rerank: bool = False,
) -> RetrievalPlan:
    """Build a deterministic RetrievalPlan for a decided intent."""
    return RetrievalPlan(
        intent=intent,
        strategy=INTENT_TO_STRATEGY[intent],
        top_k=top_k,
        enable_rerank=enable_rerank,
        reason=_INTENT_REASONS[intent],
    )
