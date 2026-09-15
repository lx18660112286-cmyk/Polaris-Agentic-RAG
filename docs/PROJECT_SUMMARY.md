# Dev Knowledge Agent — Project Summary

> 面试导向的技术总结（约 2–4 页）。面向：能讲清「做了什么、为什么这样设计、踩过哪些坑、结果如何、
> 生产化还差什么」的工程师。
> 澄清对比见 [INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md)；架构与各阶段详见 [../README.md](../README.md) 与 `docs/adr/`。

---

## Problem

开发者知识（部署文档、鉴权、事故 Runbook、服务架构）是**碎片化、多文档、强因果**的。
直接给 Agent 一个原始检索接口（`@tool -> LightRAG.aquery()`）会带来三类问题：

1. Agent 被迫理解框架细节（`QueryParam`、`local/global/hybrid`、`top_k`、`rerank`）；
2. 「要不要检索」和「怎么检索」两个决策被混成一层，既不可解释也不可复用；
3. 检索结果不可验证（citation 只给 basename、可能歧义），Agent 无从判断证据是否可靠。

`Dev Knowledge Agent` 的目标：**把 RAG Kernel（LightRAG）转化为 Agent 可以可靠使用的 Tool
（RagSearchTool）**。它是一个 Agentic RAG 参考项目，LightRAG 只是检索内核。

## Architecture

```text
                  User
                   │
                   ▼
           AgentOrchestrator        ← Agent Decision: 要不要检索（Tool Calling, LLM 原生）
                   │
                   ▼
            RagSearchTool            ← Agent-facing capability（只暴露 query）
                   │
                   ▼
             QueryRouter             ← Retrieval Decision: 怎么检索（确定性规则，无 LLM）
                   │
                   ▼
            RetrievalPlan            ← 应用自有的策略对象（intent / strategy / top_k...）
                   │
                   ▼
        KnowledgeSearchPort          ← 端口契约（框架无关）
                   │
                   ▼
          LightRAGAdapter            ← 唯一 import LightRAG 的地方（合规边界）
                   │
                   ▼
          LightRAG Kernel            ← RAG 内核（chunk/索引/检索/引用）
```

两个关键决策被**刻意分离**：
- **Agent Decision（要不要检索）** → `AgentOrchestrator` + 原生 Tool Calling。
- **Retrieval Decision（怎么检索）** → `QueryRouter` 确定性规则。

旁路：`Evaluation`（分层打分）+ `Observability`（trace_id 贯穿 Agent→Tool→Router→Adapter）。

## Major Design Decisions

1. **LightRAG is Kernel, not Agent framework。** 只借用 LightRAG 的 RAG 能力，不依赖其
   Agent / Tool / API 层。项目禁止自研任何 RAG 组件。
2. **Agent does not depend directly on LightRAG。** Agent 只见 `RagSearchTool` 与
   `KnowledgeSearchPort`，不 import LightRAG 任何类型。
3. **RagSearchTool depends on KnowledgeSearchPort。** Tool 依赖端口而非 Adapter，由 AST 架构守卫
   强制，供应商可替换。
4. **Evidence Contract belongs to the application。** `evidence/models.py` 是领域模型，形状扎根于
   Kernel 真实返回；缺失字段保持 `None` 不伪造；`SourceResolver` 处理 basename 歧义。
5. **Retrieval strategy is application-owned。** `RetrievalIntent/Strategy/Plan` 是应用概念；
   `RetrievalStrategy → LightRAG mode` 映射只藏在 Adapter 内。
6. **Agent performs final synthesis; RagSearchTool performs retrieval。** Agent 基于证据综合答案
   并引用，绝不自己控制检索参数；证据不足时诚实弃答。
7. **Evaluation is layered instead of only scoring final answer。** Layer A Tool Selection /
   Layer B Router Component / Layer C Agentic Retrieval，分层归因、无 LLM 裁判。

## Experiments

关键演进（**architecture evolved from evidence**，非一次拍脑袋）：

| Stage | 学到什么 | 驱动的后续设计 |
|---|---|---|
| 0 Bootstrap | LightRAG 是 submodule 内核，import 必须隔离 | `adapters/lightrag/` 唯一 import 边界 + AST guard |
| 1 Native E2E Baseline | Kernel 真实返回形态：citation 只有 basename、失败是 status/raise 混合 | Stage 2 Evidence Contract + SourceResolver |
| 2 RagSearchTool + Port + Adapter | Kernel/App 边界应稳定在 Tool 层 | 端口注入、workspace 隔离 |
| 3 Query Router | 路由策略属于应用层，可确定性离线测试 | `RetrievalPlan` + `_STRATEGY_TO_MODE` 藏在 Adapter |
| 4 Single Agent | Agent 需要自主决定是否检索 | 原生 Tool Calling + 终止防护 |
| 5 Evaluation + Observability | 指标必须确定性、可复现；trace 贯穿全链 | 无 LLM 裁判 + `.local/eval/` 落盘 |
| 5.1 Stabilization | 路由聚合用 last-write-wins 会误报失败 | `RoutingStep` + primary=首决策 + 三层评估 |

## Key Findings

- **分层评估是最有价值的发现。** Stage 5 单一混合 routing 指标把「Router 自身缺陷」与
  「Agent 改写导致的漂移」混在一起（曾显得只有 60%）；Stage 5.1 拆三层后，Router Component 本身
  达到 90%/93.3%，Agentic 侧 89.7%/93.1%，并精确定位了 3 例改写漂移。
- **Query rewrite 有用但会改变路由特征。** Agent 改写查询可能丢「是什么」等路由 marker → intent
  flip。这是已接受的 trade-off，通过 Query Provenance + Layer B/C 分离暴露，而非强制 verbatim。
- **Kernel 的引用只给 basename 且可能歧义。** 直接使用会在多文档中选错来源；`SourceResolver` 三态
  （RESOLVED/UNRESOLVED/AMBIGUOUS）保证绝不静默选错。
- **LightRAG 去重按 workspace 而非 working_dir。** 并发/隔离测试会误判重复文档，需显式 workspace 隔离。

## Evaluation Results

**37 例 / 9 类**（`.local/eval/eval-<ts>.json`，真实 DeepSeek + Ollama bge-m3 + LightRAG 02dcd8d）。

| Metric | Value |
|---|---:|
| Tool Selection Accuracy / Precision / Recall | **97.3%** / 100.0% / 96.7% |
| Router Component Intent / Strategy | **90.0%** / **93.3%** |
| Primary Agentic Intent / Strategy | 89.7% / 93.1% |
| Citation Groundedness | **100.0%** |
| Abstention Accuracy | **100.0%** |
| Expected Source Recall | 96.0% |
| System failures | 0 |
| Latency p50 / p95 | 3453.0 / 5401.8 ms |
| Tokens per case | 4260.7 |

## Engineering Trade-offs

- **确定性路由 vs 语义灵活性。** Router 用规则（可离线测试、可解释）换取对复杂自然语言的覆盖面
  有限（t4/r4/m4 规则边界）。不引入 LLM 路由，避免不可复现与成本。
- **Agent 改写 vs 路由稳定性。** 保留改写能力（Agent 更自然）换取 3 例 intent drift，用分层评估兜底。
- **不刷指标 vs 完美分数。** 保留 f3 FN、router 边界、rewrite drift，**不做 per-query hardcode、
  不删除失败 case、不加 keyword soup**（spec §3）。
- **`total_tokens` 只统计 Agent 调用。** Kernel 内部 LLM token 无法可靠获取，不冒充系统 total。

## Known Limitations

1. `f3`（"401 和 403 有什么区别"）归为 generic HTTP knowledge 直答，未调工具（FN=1），事实正确。
2. Router 规则边界 3 例（t4/r4/m4）："scope" 未识别为术语、"…是什么关系" 误判 terminology、
   "如何诊断" 触发 relational 倾向。
3. Query rewrite drift 3 例（g2/i1 真实漂移，f3 为副作用），已按 QUERY_REWRITE_INTENT_DRIFT 归因。
4. Kernel 内部 LLM token 不可统计。
5. Latency 主体在 LightRAG 检索（p95 ≈ 5.4s）。

## What I Would Do Next In Production

（当前为参考项目，未进入生产；以下为真实生产化优先级，按风险收益排序）

1. **确定性 reranker 评估**：衡量 reranker 对 source recall / citation 的提升，决定是否启用。
2. **LLM-in-the-loop 路由做 A/B**：在现规则之上，对规则低置信 case 用 LLM 兜底，并离线评测收益。
3. **更大规模知识库 + 评估回归**：扩充 37 例数据集，验证扩展到数百/数千文档时指标是否保持。
4. **MCP 暴露 `RagSearchTool`**：把领域能力标准化给外部消费。
5. **服务化 + 鉴权 + 多租户 + 观测接入**：Docker 部署、请求级追踪接入生产链路、成本与延迟告警。
6. **外部开发工具（Git/Log/DB/Web）**：在原 Stage 6 方向演进为 Multi-Tool Agent —— 但那是
   **另一个产品**，不在当前交付范围。