# Dev Knowledge Agent — Interview Guide

> 作者本人面试准备。非营销话术，全部基于项目**真实实现**。对每个问题给出「答案 + 项目里对应在哪」，
> 便于一边讲一边引用代码/文档。技术总结见 [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)。

---

## 一、30 秒项目介绍

> 直接背这一段（spec §27）：

这是一个**基于 LightRAG 的 Agentic RAG 项目**。我没有让编排层直接依赖 LightRAG，而是通过
**RagSearchTool、KnowledgeSearchPort 和 LightRAGAdapter** 隔离 Kernel。系统会先**动态判断问题是否
需要知识检索**（Retrieval Invocation），再由 **QueryRouter** 根据问题意图生成 **RetrievalPlan**，
最终把 LightRAG 的实体、关系、chunk 和 citation **归一化成应用自己的 Evidence Contract**，由上层
**基于证据回答或拒答**（Grounded Synthesis / Abstention）。同时我做了**分层 evaluation** 和
**tracing**，分别评估 retrieval invocation、retrieval planning、citation 和 abstention。

## 二、2 分钟架构介绍

讲清链路与**为什么这么分层**：

```text
Agentic RAG Orchestrator
   ↓  Retrieval Invocation（要不要检索）
RagSearchTool
   ↓  Retrieval Planning（怎么检索）
QueryRouter → RetrievalPlan
   ↓
KnowledgeSearchPort
   ↓
LightRAGAdapter
   ↓
LightRAG Kernel
```

1. **Agentic RAG Orchestrator**：只有一个决策——直接回答还是检索（Retrieval Invocation）。用原生
   function calling，不自制文本协议。
2. **RagSearchTool**：把「知识检索」包装成稳定、只收 `query` 的领域能力，隐藏一切 Kernel 细节。
3. **QueryRouter**：唯一知道「怎么检索」的地方，用**确定性规则**（无 LLM、离线可测），产出
   RetrievalPlan。
4. **KnowledgeSearchPort**：框架无关的契约，保证 Tool 不依赖具体供应商。
5. **LightRAGAdapter**：全项目唯一 import LightRAG 的地方，把策略→mode 映射等藏在这一层。
6. **LightRAG**：真正的外部 RAG Kernel——文档处理、chunk、索引、检索、引用。

**为什么这样分层**：职责单一、可替换（换内核只动 Adapter）、可测（Router/评估离线）、编排层无供应商
依赖。收尾一句：*Kernel 是内核，App 是壳，之间用契约（Evidence Contract）隔开。*

## 三、5 分钟技术深挖（architecture evolved from evidence）

按阶段讲「每次都是被真实运行/评估逼出来的」，这是最有说服力的讲法：

- **Stage 1 实验**：先不实现架构，直接跑原生 LightRAG，**记录它真实返回什么**。
  发现：citation 只有 basename、失败 API 混合 raise/status、`working_dir` 不隔离去重。
- **Stage 2 契约**：基于观察设计 Evidence Contract + `SourceResolver`（三态解决 basename 歧义），
  workspace 隔离去重。
- **Stage 3 路由**：因为 Agent 不该知道 mode/top_k，把检索策略做成应用层 `RetrievalPlan`，规则路由。
- **Stage 4 Agent**：用原生 Tool Calling 让 Agent 自己决定要不要检索，终止防护防死循环。
- **Stage 5/5.1 评估**：先发现「末次路由覆盖首次决策」的聚合伪失败；再拆三层，把 Router 自身缺陷与
  Agent 改写漂移分离，精确定位 3 例 rewrite drift、1 例 FN。

收尾：*每一步架构决定都来自上一阶段的证据，不是拍脑袋。*

---

## 四、20 个面试问题（真实实现作答）

### 1. 为什么这是 Agentic RAG，而不是普通 RAG？
普通 RAG 是 `Query → Fixed Retrieval → Context → LLM`，检索方式是固定的。本项目在每次查询**运行时**
动态决定「要不要检索」（Retrieval Invocation）、「怎么检索」（Retrieval Planning），再基于证据做
grounded synthesis 或 abstention —— 决策发生在运行时，因此是 Agentic RAG。（`README §Why Agentic RAG`）

### 2. Agentic 体现在哪里？
体现在**运行时决策**而不是工具数量：① 动态判断是否需要检索；② 动态规划检索策略；③ evidence-aware
合成与弃答。我把「用了 function calling」只当作实现手段，不当作 Agentic 的理由。（`agent/orchestrator.py`）

### 3. 为什么不直接 Agent → LightRAG？
直接耦合会让编排层被迫理解 `QueryParam/mode/top_k/rerank`，检索参数写死、不可解释、难复现，换内核要
改上游。中间用 `RagSearchTool → Port → Adapter` 隔离，把 Kernel 细节挡在 Adapter 内。（`docs/adr/0001`）

### 4. 为什么需要 RagSearchTool？
它是**Agentic RAG knowledge retrieval capability boundary**：把「知识检索」封装成只收 `query`、
返回归一化证据与引用的领域能力，隐藏 Kernel 细节。它既不是 generic tool platform，也不是 LightRAG
的薄包装。（`tools/rag_search.py`、`README`）

### 5. 为什么需要 KnowledgeSearchPort？
Port 定义**框架无关**的检索契约，让 Tool / 上层只依赖抽象、不依赖 LightRAG 实现。这样「换内核」只改
Adapter，上游零改动。（`protocols/knowledge_search.py`）

### 6. Adapter 解决什么问题？
`LightRAGAdapter` 是唯一 import LightRAG 的地方：映射应用策略→真实 mode、调用 `aquery_data`、隔离 Kernel
异常、做 storage lifecycle、用 SourceResolver 还原 citation 路径、管理 workspace 隔离。
（`adapters/lightrag/adapter.py`）

### 7. Evidence Contract 为什么由应用定义？
因为**检索结果的语义属于应用**，不属于 Kernel。应用定义什么算证据、缺失如何表示、citation 是否可用。
否则上层会紧贴复杂易变的 Kernel 返回结构，无法替换与演进。（`evidence/models.py`）

### 8. Retrieval Invocation 是什么？
`Decision A — Should retrieval happen?`：要不要检索。由 Orchestrator 用原生 function calling 动态判定。
例如 `你好 → No Retrieval`，`Access token 的有效期是多少 → Retrieval`。（`agent/orchestrator.py`）

### 9. Retrieval Planning 是什么？
`Decision B — How should retrieval happen?`：给定 query 怎么检索。由确定性 `QueryRouter` 产出
`RetrievalPlan`（intent/strategy/top_k/rerank/reason），如 `FACTUAL → FOCUSED`、`MULTI_DOCUMENT → HYBRID`。
（`retrieval/router.py`）

### 10. 两者为什么拆开？
「要不要检索」是**行为决策**（Agentic 层），「怎么检索」是**策略决策**（检索层），关注点不同。
写在同一层会既不可解释也不可复用，也无法各自独立度量与评估。（`README §两个决策层`）

### 11. QueryRouter 为什么不用 LLM？
LLM 路由不可复现、有成本与延迟、难离线测试。确定性规则保证**可解释、可审计、零成本**，并可把路由
结果透出供评估；规则边界（t4/r4/m4）是已知 trade-off。（`retrieval/rules.py`）

### 12. 为什么 Agent 不直接指定 hybrid/local？
因为「怎么检索」是**应用策略**不是模型行为。让 Agent 控制会导致检索参数不可预测、难复现。策略由
`QueryRouter` 确定性产出，再在 Adapter 内部映射到真实 mode。（`adapters/lightrag/_STRATEGY_TO_MODE`）

### 13. 为什么 RagSearchTool 不生成最终答案？
检索与合成是两层职责：`RagSearchTool` 负责 Retrieval（返回归一化证据 + citation），Grounded Synthesis
由 Orchestrator 负责。分离使「检索正确性」与「合成正确性」能独立评估与修复。（`tools/rag_search.py`、`agent/`）

### 14. Agentic RAG 如何处理 unknown questions？
`evidence_availability = NONE` 或证据不足时，prompt 引导**诚实弃答**而非编造。Abstention Accuracy = 100%，
`NO_EVIDENCE` 与系统失败在 failure taxonomy 里分离。（`agent/prompts.py`、`observability/models.py`）

### 15. citation 如何保证 grounded？
Groundedness 检查：答案里每个引用必须对应 evidence 的 citation。SourceResolver 保证 basename 还原不歧义
（三态，绝不明选）。37 例 Groundedness = 100%。（`evaluation/metrics.py`、`source_resolver.py`）

### 16. Query rewrite drift 是什么？
Orchestrator 为了让查询更像“检索查询”可能改写它，丢掉「是什么/是多少」等**路由 marker** 导致 intent
翻转（如 terminology → multi_document）。我用 `critical_term_preservation_rate`（96.7%）+ Layer B/C
分层评估把它量化归因，而不是禁止改写。（`docs/STAGE5_1` §1.4）

### 17. 为什么 Evaluation 要分层？
单看最终答案无法定位错误来自哪一层：Retrieval Invocation 没触发？Router 分错？改写漂移？证据没命中？
还是合成不接地？Layer A–E 分层后用确定性指标**归因到具体环节**。（`evaluation/`、`docs/STAGE5_1`）

### 18. LightRAG 如果替换掉，需要改哪些代码？
理论上只改 `adapters/lightrag/`：新 Adapter 实现 `KnowledgeSearchPort`、把新内核输出映射回 Evidence
Contract、把策略→mode 映射留在内部。Tool / Orchestrator / 评估零改动。这正是 Port + Adapter +
Evidence Contract 的隔离价值（可做一个真实换内核 A/B 实验验证）。

### 19. 当前最大 limitation 是什么？
**Kernel 内部 token 与检索延迟不可完全观测**（`total_tokens` 只统计 Orchestrator 的 DeepSeek usage，
p95 ≈ 5.4s 主体在 LightRAG 检索），生产里成本/延迟组成不透明。其次，确定性路由对复杂自然语言有
规则边界（t4/r4/m4），reranker 未评估。

### 20. 如果投入生产下一步会做什么？
确定性 reranker 评估 → 更大知识库 + 评估回归 → 服务化 + 鉴权 + 多租户 + 生产链路观测 → MCP 暴露
`RagSearchTool` → 替代 Kernel A/B。按风险收益排序，不是一次性全上。（`PROJECT_SUMMARY §Production`）

---

## 五、Demo Flow（用 `scripts/run_agent.py`）

> 不新增功能，基于现有 CLI。Queries 3 & 4 的检索与弃答由 Orchestrator 自主触发，实跑以输出为准。

| 步骤 | 期望展示 |
|---|---|
| **Query 1**：`你好` | **Retrieval Invocation = false**（直接回答，无检索） |
| **Query 2**：`Access token 的有效期是多少？` | Retrieval Invocation = true → `search_dev_knowledge` → FACTUAL/FOCUSED → `[api_auth.md]` → grounded answer + citation |
| **Query 3**：`Order Service 发布后出现大量 5xx，应该如何排查并判断是否回滚？` | Retrieval → MULTI_DOCUMENT → 多来源证据 → grounded synthesis |
| **Query 4**：`Billing Service 使用什么数据库？` | Retrieval → evidence 不足 → **abstain**（拒绝幻觉） |
| **--debug**：重跑任一 Query | 展示 `trace_id` / retrieval invocation / tool query / retrieval intent / retrieval strategy / citations / latency。**不输出 chain-of-thought**（sink 前自动脱敏） |

## 六、Debug 展示台词

```text
trace_id: 贯穿一次请求
TOOL_SELECTED      工具是否被选中
TOOL_CALL_STARTED  发给 search 的 query（改写前后可对比）
ROUTER_DECISION    intent / strategy / reason / fallback
RETRIEVAL          evidence 数量与来源
TOOL_CALL_COMPLETED 引用与延迟
```

这些来自 `scripts/run_agent.py --debug` 打印的真实事件，不展示模型思维链。