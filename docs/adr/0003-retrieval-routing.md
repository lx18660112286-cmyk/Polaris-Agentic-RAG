# ADR 0003 — Retrieval Routing（QueryRouter → RetrievalPlan）

- **Status**: Accepted
- **Date**: 2026-09-15
- **Relates to**: ADR 0001, ADR 0002

## Context

ADR 0001 / ADR 0002 把检索参数（`mode / top_k / rerank`）藏在 `LightRAGAdapterSettings` 里，
由 Adapter 的默认配置固定决定（Stage 2 统一走 `default_query_mode="hybrid"`）。

问题在于：**"如何检索" 是应用策略，不应由 Kernel 配置长期决定**。

- 不同用户意图（精确事实 / 术语 / 关系 / 跨文档排查 / 全局概览）在 Stage 1 观察中倾向于不同
  检索形态（local 聚焦实体、global 概览、hybrid 图+chunk、naive 纯向量、mix 图+向量）。
- 如果始终 hybrid，跨文档 / 关系类问题的检索质量无法与聚焦类问题分离调优。
- 未来若要换 Kernel，或做模式对比评估，需要一个稳定的应用层"检索决策"概念。

同时约束明确：
- Agent / Caller 仍然只提供 `query`，不得直接指定 `mode / top_k / chunk_top_k / enable_rerank / QueryParam`。
- 只有 `adapters/lightrag/` 知道 LightRAG QueryParam 与真实 mode 字符串。
- Router 绝不能 import LightRAG。
- 不能用 LLM classifier（保持 deterministic / explainable / cheap / offline-testable）。

## Decision

采用"应用层路由"：

```text
RagSearchTool
    ↓
QueryRouter
    ↓
RetrievalPlan
    ↓
KnowledgeSearchPort
    ↓
LightRAGAdapter
    ↓
QueryParam  (only here)
    ↓
LightRAG
```

关键判断：

1. **`RetrievalStrategy` 是应用自有的策略枚举**（`FOCUSED / GLOBAL / HYBRID / VECTOR / MIXED`），
   不是 LightRAG 的 `local/global/hybrid/naive/mix` 字符串。映射（`FOCUSED→local`、`VECTOR→naive`…）
   只在 `adapters/lightrag/adapter.py` 的 `_STRATEGY_TO_MODE` 中。
2. **`RetrievalIntent`** 是用户意图（`FACTUAL / TERMINOLOGY / RELATIONAL / MULTI_DOCUMENT /
   OVERVIEW / GENERAL`），用于让路由结果可解释。
3. **`RetrievalPlan`** 携带 `intent / strategy / top_k / chunk_top_k / enable_rerank / reason`，
   是 Router 的产物，框架无关，禁止出现 vendor 类型。
4. **`QueryRouter.route(query) -> RetrievalPlan`** 采用**确定性规则**（`retrieval/rules.py`，
   QueryFeatures → decide_intent → strategy）。无网络 / 无 LLM / 离线可测。
5. **Fallback 是显式且可观测的**：Router 异常时返回安全 hybrid plan，并把 `fallback_used=True`
   暴露在 `RoutingDecision` 中（附带在 `RagSearchResult.routing`）；禁止 silent fallback。
6. **`KnowledgeSearchPort.search(query, *, plan=None)`**：`plan=None` 时 Adapter 用默认策略；
   Tool 正常路径始终传入 Router 生成的 plan。
7. **`RagSearchTool` 只增加 Router 依赖注入**，输入仍只有 `query`；`RagSearchResult` 附带
   `routing: RoutingDecision | None` 供调试 / 测试 / Stage 5 observability。
8. **移除公共契约里的 vendor 诊断**：`RetrievalDiagnostics.query_mode` 被移除；真实的
   LightRAG `mode` 只存在于 Adapter 内部。
9. **rerank 默认关闭**：Stage 1 未配置 reranker，`RetrievalPlan.enable_rerank` 默认为 `False`，
   不因字段存在就临时引入 reranker provider。

### GENERAL 回退策略（GENERAL → HYBRID）

Stage 1 观察：hybrid 同时召回 entity + relationship，跨文档与聚焦场景都能给出可用上下文，
且是默认的 kernel 模式，成本/行为最稳定。因此不明确的 GENERAL 问题选择 `HYBRID` 作为安全默认。

### 意图 → 策略映射（Stage 1 依据）

| Intent | Strategy | LightRAG mode | Stage 1 依据 |
|---|---|---|---|
| FACTUAL | FOCUSED | `local` | local 实体级聚焦召回 |
| TERMINOLOGY | FOCUSED | `local` | 术语 → 实体定义 |
| RELATIONAL | HYBRID | `hybrid` | 关系问题 → 图+chunk |
| MULTI_DOCUMENT | HYBRID | `hybrid` | 跨文档排查 → 综合召回 |
| OVERVIEW | GLOBAL | `global` | 概览 → 关系/全局级 |
| GENERAL | HYBRID | `hybrid` | 安全回退 |

## Alternatives Considered

### Option A — Router 直接输出 LightRAG mode / QueryParam

**拒绝。** 让应用层以 Kernel 类型为核心模型 → vendor coupling；Router 将被迫 import LightRAG / QueryParam，
违反 §2 最重要边界。

### Option B — LLM Router

**拒绝（暂缓）。** 无法区分"路由改进"与"LLM 随机性"，且昂贵、不可离线测。先以确定性规则建立
routing baseline，未来用 Evaluation 数据证明必要后再评估。

### Option C — Tool 不变，仅 Adapter 内部策略

**拒绝。** 检索决策仍不可解释、不可独立测试、无法为每个 intent 调优；无法为 Stage 5 Evaluation / Tracing
提供挂载点。

## Consequences

正面影响：
- "如何检索"上升为应用层可解释、可测试、可调优的策略；
- Agent 与 Caller 永不接触 Kernel 参数；边界由 `tests/architecture` 强制（`retrieval/` 不得 import
  lightrag / adapters / tools / agent）；
- 为 Stage 5 评估（mode 对比）、Tracing、以及"是否需要 LLM Router"提供稳定 baseline。

代价：
- 多一层 Router → Plan 映射，需要一套确定性规则与充足的单测；
- 规则基于当前 KB 的措辞，换领域需重设计（规则写在 `retrieval/rules.py`，已集中且可改）；
- fallback 语义需在所有层保持一致（Router 显式 + Tool `routing` 透出）。

## When To Revisit

- 引入第二个 RAG Kernel 时：`_STRATEGY_TO_MODE` 是唯一需要新增映射的地方。
- 有 Evaluation 证据表明某一类 intent 应换策略 / 切换 LLM Router 时。
- 领域 / 知识库措辞发生大变化，导致规则命中率下降时。