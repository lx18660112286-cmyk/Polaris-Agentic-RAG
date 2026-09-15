# Polaris Agentic RAG — Project Summary

> 面试导向的技术总结（约 2–4 页），围绕 **Agentic RAG** 而非 generic Agent framework。
> 澄清对比与逐题准备见 [INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md)；架构与各阶段详见
> [../README.md](../README.md) 与 `docs/adr/`。

一句话：**Polaris Agentic RAG is an Agentic RAG system** that dynamically decides whether retrieval
is required, plans how retrieval should be executed, normalizes LightRAG kernel output into
structured evidence, and performs grounded synthesis or abstention with layered evaluation and
observability.

---

## Problem

开发者知识（部署文档、鉴权、事故 Runbook、服务架构）是**碎片化、多文档、强因果**的。直接把
Knowledge retrieval 暴露给上层带来三类问题：

1. 上层被迫理解框架细节（`QueryParam`、`local/global/hybrid`、`top_k`、`rerank`）；
2. 「要不要检索」和「怎么检索」两个决策混成一层，既不可解释也不可复用；
3. 检索结果不可验证（citation 只给 basename、可能歧义），上层无从判断证据是否可靠。

## Why Agentic RAG

```text
Traditional RAG:        Query → Fixed Retrieval → Context → LLM
Agentic RAG（本项目）:   User Query → Retrieval Invocation → Retrieval Planning
                      → Dynamic Retrieval → Evidence Normalization
                      → Grounded Synthesis → Answer / Abstain
```

Agentic 的来源是**运行时决策**（Retrieval Invocation + Retrieval Planning + evidence-aware
synthesis），而不是「用了 function calling」或「工具数量」。

## Architecture

```text
User Query → Agentic RAG Orchestrator
               │  Retrieval Invocation
               ├── No Retrieval ──────────────▶ Grounded Synthesis
               └── Retrieval ──▶ RagSearchTool ─▶ QueryRouter ─▶ RetrievalPlan
                                ─▶ KnowledgeSearchPort ─▶ LightRAGAdapter ─▶ LightRAG Kernel
                                ─▶ Evidence ─▶ Grounded Synthesis ─▶ Answer / Abstain
                  （旁路 Evaluation + Observability）
```

依赖边界：`RagSearchTool → KnowledgeSearchPort（implemented by LightRAGAdapter）→ LightRAG`。
只有 `adapters/lightrag/` 可 import LightRAG；`ToolRegistry` 只是 native function calling 的
内部执行机制。

## Retrieval Invocation

`Decision A — Should retrieval happen?`

由 Agentic RAG Orchestrator 用原生 function calling（`tool_choice="auto"`）动态判定：

```text
你好                           → No Retrieval
Access token 的有效期是多少？  → Retrieval
```

这是 **Agentic RAG orchestration decision**，不是 multi-tool selection。

## Retrieval Planning

`Decision B — How should retrieval happen?`

由确定性 `QueryRouter` 产出 `RetrievalPlan`（intent / strategy / top_k / rerank / reason）：

```text
FACTUAL → FOCUSED    OVERVIEW → GLOBAL    MULTI_DOCUMENT → HYBRID
TERMINOLOGY → FOCUSED  RELATIONAL → HYBRID   GENERAL → HYBRID（显式 fallback）
```

优先级：`OVERVIEW > TERMINOLOGY > RELATIONAL > MULTI_DOCUMENT > FACTUAL > GENERAL`。
无网络、无 LLM、离线可测；`RetrievalStrategy → LightRAG mode` 映射藏在 Adapter 内。

## Evidence Contract

`evidence/models.py` 定义框架无关、应用自有的证据模型（query / evidence / citations /
diagnostics / evidence_availability）。**缺失字段不伪装、SourceResolver 解决 basename 歧义、
异常归一化**。Kernel → 领域模型不泄漏 vendor 类型。

## Grounded Synthesis

`Decision C — What can be safely answered from retrieved evidence?`

仅在证据可用时综合答案并引用；`evidence_availability = NONE` 或证据不足时**诚实弃答**。
Orchestrator 负责合成，`RagSearchTool` 负责检索，二者职责分离。

## Evaluation

分层评估（全部确定性指标，**无 LLM 裁判**，结果在 `.local/eval/` 可复现）：

| Layer | 衡量 |
|---|---|
| **A — Retrieval Invocation** | should retrieval be triggered?（Accuracy/Precision/Recall/FP/FN） |
| **B — Retrieval Planning** | Router 对原始查询的分类（Intent/Strategy/Fallback） |
| **C — Agentic Retrieval Execution** | Orchestrator+改写经 Router 的首决策（Rewrite Drift / Preservation） |
| **D — Retrieval / Evidence** | Expected Source Recall / Citation Source Recall |
| **E — Grounded Synthesis** | Answer Term Match / Citation Groundedness / Abstention |

## Key Engineering Findings

真实项目经验（每一步都由证据驱动）：

- **LightRAG basename citation**：Kernel 丢失原始路径 → `SourceResolver` 三态还原。
- **Workspace isolation**：`working_dir` ≠ dedup 隔离 → 显式 `workspace`。
- **Lifecycle failure**：pre-init query 泄漏 TypeError → Adapter lifecycle guard。
- **Evaluation aggregation**：`last-write-wins` 造成伪失败 → `RoutingStep` + primary=首决策。
- **Query rewrite drift**：Agent 改写改变检索意图 → Query Provenance + 分层评估归因。

## Known Limitations

- 小知识库；37 例有限评估集（非大规模统计）。
- 确定性 Router 有规则边界 case（t4 / r4 / m4）。
- Query 重写可能造成 retrieval-intent drift（3 例）。
- Reranker 未评估。
- Kernel 内部 LLM token 不可统计（`total_tokens` 只计 Orchestrator 的 DeepSeek usage）。
- Latency 主体在 LightRAG 检索（p95 ≈ 5.4s）。
- Provider / model 行为可能变化。

## Production Considerations

（参考项目未进入生产；以下为真实生产化优先级，按风险收益排序）

1. 确定性 reranker 评估，衡量对 Source Recall / Citation 的提升。
2. 更大规模知识库 + 评估回归（扩充 37 例）。
3. 服务化 + 鉴权 + 多租户 + 生产链路观测接入。
4. MCP 暴露 `RagSearchTool`；LLM-in-the-loop 路由 A/B。
5. 替代 RAG Kernel 的 A/B 实验，验证 Port/Adapter 隔离可替换性。（均 Not part of current scope）