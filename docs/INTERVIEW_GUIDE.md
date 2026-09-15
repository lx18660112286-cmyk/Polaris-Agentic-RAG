# Dev Knowledge Agent — Interview Guide

> 作者本人面试准备。非营销话术，全部基于项目**真实实现**。对每个问题给出「答案 + 项目里对应在哪」，
> 便于一边讲一边引用代码/文档。技术总结见 [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)。

---

## 一、30 秒项目介绍

> 背下来，覆盖：Agentic RAG / LightRAG Kernel / RagSearchTool / Retrieval Router / Agent Tool Calling / Evaluation。

Dev Knowledge Agent 是一个 **Agentic RAG 应用**，用 **LightRAG 作检索内核**。

核心不是 `Agent → LightRAG`，而是中间加了一层：Agent 通过原生 **Tool Calling** 自主决定「要不要检索」，
一旦要检索，就调用 `RagSearchTool`——一个只暴露 `query` 的领域能力。工具内部由确定性的 **Retrieval Router**
决定「怎么检索」（事实/术语/多文档/全局），并经 `Port → Adapter` 落到 LightRAG，返回带引用的结构化证据。

我把评估做成**分层**（Agent 选工具、路由器自身、Agent 检索链路三分离，无 LLM 裁判），并用观测 trace 贯穿整条链。

## 二、2 分钟架构介绍

讲清链路与**为什么这么分层**：

```text
Agent → Tool → Router → Port → Adapter → LightRAG
```

1. **Agent**：只要做一个决定——直接回答还是检索。用 provider 原生 Tool Calling，不自制文本协议。
2. **Tool（RagSearchTool）**：把「检索」包装成稳定、只收 `query` 的领域能力，隐藏一切 Kernel 细节。
3. **Router（QueryRouter）**：这是唯一知道「怎么检索」的地方，用**确定性规则**（无 LLM、离线可测）。
4. **Port（KnowledgeSearchPort）**：框架无关的契约，保证 Tool 不依赖具体供应商。
5. **Adapter（LightRAGAdapter）**：全项目唯一 import LightRAG 的地方，把 `RetrievalStrategy → mode`
   等映射藏在这一层。
6. **LightRAG**：真正的内核——文档处理、chunk、图向量索引、检索、引用。

**为什么这样分层**：职责单一、可替换（换内核只动 Adapter）、可测试（Router 离线测）、Agent 无供应商依赖。
用一句台词收尾：*Kernel 是内核，App 是壳，之间用契约隔开。*

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

### 1. 为什么用 LightRAG？
因为它把一整条 RAG pipeline（chunk、entity/relation 抽取、图 + 向量双索引、hybrid 检索、上下文构建、
引用数据）都做了。我**不该自研**这些；我要做的是它没有的 Agentic 层。且源码可控（submodule pinned），
能读懂它在返回什么。（见 `docs/adr/0001`、`docs/LIGHTRAG_SOURCE_INTEGRATION.md`）

### 2. 为什么不直接 `@tool -> LightRAG.aquery()`？
因为那样 Agent 会碰 `QueryParam/mode/top_k/rerank`，检索参数写死、不可解释、不可复现，而且换供应商
要改 Agent。直接耦合违背「Agent 面向领域能力」的原则。（`README §Why RagSearchTool`）

### 3. 为什么需要 Adapter？
Adapter 是全项目唯一 import LightRAG 的地方，负责：把应用 `RetrievalStrategy` 映射成真实 `mode`、
调用 `aquery_data`、隔离 Kernel 异常、做 storage lifecycle、用 SourceResolver 还原 citation 路径。
（`adapters/lightrag/adapter.py`，由 AST 守卫强制）

### 4. 为什么需要 Port？
Port（`KnowledgeSearchPort`）定义**框架无关**的检索契约，让 Tool 只依赖抽象、不依赖供应商实现。
这样「换掉 LightRAG」只改 Adapter，Tool 和 Agent 层零改动。（`protocols/knowledge_search.py`）

### 5. Evidence Contract 有什么意义？
它把 Kernel 杂乱的返回归一化为应用领域模型：query / evidence / citations / diagnostics /
evidence_availability（NONE/PRESENT/TRUNCATED）。**缺失字段不伪装、SourceResolver 解决歧义、异常归一化**。
Agent 从此能判断证据是否足够，进而决定直答、引用还是弃答。（`evidence/models.py`）

### 6. 为什么 Agent 不直接控制 mode/top_k？
因为「怎么检索」是**应用策略**不是模型行为。让 Agent 控制会导致检索参数不可预测、难复现。
RetrievalPlan 由 Router 确定性产出。（`retrieval/models.py`、`adapters/lightrag/_STRATEGY_TO_MODE`）

### 7. Query Router 怎么设计？
确定性优先级规则：`OVERVIEW > TERMINOLOGY > RELATIONAL > MULTI_DOCUMENT > FACTUAL > GENERAL`。
输入 query → 输出 `RetrievalPlan`（intent/strategy/top_k/rerank/reason）+ `RoutingDecision`；异常走显式
fallback（`fallback_used=True`）。无网络、无 LLM、离线可测。（`retrieval/rules.py`、`router.py`）

### 8. 为什么 Router 不用 LLM？
LLM 路由不可复现、有成本与延迟、难离线测试。本项目用确定性规则保证**可解释、可审计、零成本**，
并把路由结果透出在 `RagSearchResult.routing` 供评估。规则边界（3 例）是已知 Trade-off，而非随性决策。

### 9. Agent 为什么不用 LangGraph？
项目只需要几十行的原生 Tool Calling 状态机：`max_steps/max_tool_calls/重复调用拒绝`。引入图框架
是过度设计；原生实现更透明、更好测试。（`agent/orchestrator.py`）

### 10. Tool Calling Loop 怎么实现？
`tool_choice="auto"`：LLM 决定要不要调 `search_dev_knowledge`；Agent 在一个循环里执行工具、把
结构化结果回填给模型，直到终点 / 触顶 / 拒调。用 Tracer 记录 TOOL_SELECTED/CALL/COMPLETED，
`tool_call_id` 关联查询。（`agent/orchestrator.py`、`observability/`）

### 11. 怎么避免 hallucination？
两层：① Agent 只在有证据时综合答案，证据不足走「诚实弃答」；② 只引用返回的 citation，不给来源就
不编来源。评估用 Citation Groundedness 100% 验证。（`agent/prompts.py`、`evaluation/`）

### 12. citation 怎么验证？
Groundedness 检查：答案里每个引用必须对应 evidence 的 citation；否则扣分。SourceResolver 保证
basename 还原不歧义。37 例 Groundedness = 100%。（`evaluation/metrics.py`）

### 13. unknown question 怎么处理？
`evidence_availability = NONE` 或证据不足时，prompt 引导 Agent 拒答而非编造。Abstention Accuracy = 100%，
`NO_EVIDENCE` 与系统失败在 failure taxonomy 里分离。（`observability/models.py`、`agent/prompts.py`）

### 14. 为什么需要 Observability？
要能回答「这个问题为什么这样答」：一个 trace_id 贯穿 Agent→Tool→Router→Adapter，记录 tool 选择、
改写前后查询、路由意图/策略、引用、延迟、token。没有它无法做分层评估、无法定位 rewrite drift。
（`observability/tracer.py`、`sinks.py`）

### 15. Evaluation 为什么分层？
单看 final answer 无法区分错误来自哪：Agent 没选对工具？Router 分类错了？还是 Agent 把查询改写坏
导致 Router 分错？拆成 Layer A/B/C 后能**归因到具体环节**。（`evaluation/`、`docs/STAGE5_1`）

### 16. Tool Selection 与 Retrieval Routing 有什么区别？
- **Tool Selection**：End-to-end 的**要不要检索**（Agent/Tool 层）。
- **Retrieval Routing**：给定 query，**怎么检索**（Router 层）。
一个是 Agent Decision，一个是 Retrieval Decision，不能混用；这也是为什么我不把它们统称 `Router`。

### 17. Query rewrite drift 是什么？
Agent 为了让查询更像“检索查询”会改写它，可能丢掉「是什么/是多少」等**路由 marker**，导致 intent
翻转（如 terminology → multi_document）。我用 `critical_term_preservation_rate`（96.7%）+ 分层评估
把它量化并归因，而不是禁止改写。（`docs/STAGE5_1` §1.4）

### 18. 如果换掉 LightRAG，需要改哪里？
理论上只改 `adapters/lightrag/`：新的 Adapter 实现 `KnowledgeSearchPort`，把新内核的输出映射回
Evidence Contract，新 strategy→mode 映射留在内部。Tool/Agent/评估层零改动——这正是
Port + Adapter + Evidence Contract 的价值。需要有一个真实换内核实验去验证（见 Optional Future Work）。

### 19. 如果进入生产环境，你会补什么？
见 PROJECT_SUMMARY「What I Would Do Next」：确定性 reranker 评估 → 更大 KB 回归 → MCP 暴露 →
服务化 + 鉴权 + 多租户 + 生产链路观测接入。按风险收益排序，不是一次性全上。

### 20. 当前最大 limitation 是什么？
**Kernel 内部 token 与检索延迟不可完全观测**（`total_tokens` 只统计 Agent 调用，p95 ≈ 5.4s 主体在
LightRAG 检索）。这意味着在生产里成本与延迟的真实构成不透明。其次，确定性路由对复杂自然语言有
规则边界（t4/r4/m4），是已知能力上限。

---

## 五、Demo Flow（用 `scripts/run_agent.py`）

> 不新增功能，基于现有 CLI。Queries 3 & 4 的多步与弃答由 Agent 自主触发，实跑以输出为准。

| 步骤 | 期望展示 |
|---|---|
| **Query 1**：`你好，请介绍一下你能做什么。` | Agent 直接回答，**0 tool calls**（无检索） |
| **Query 2**：`Access token 的有效期是多少？` | Agent → `search_dev_knowledge` → FACTUAL/FOCUSED → `[api_auth.md]` → answer + citation |
| **Query 3**：`Order Service 发布后出现大量 5xx，应该如何定位并决定是否回滚？` | MULTI_DOCUMENT → 检索 → 多来源证据 + 引用 |
| **Query 4**：`Billing Service 使用什么数据库？` | 检索 → evidence 不足 → Agent **拒绝幻觉**（诚实弃答） |
| **--debug**：重跑任一 Query | 展示 `trace_id` / tool selection / tool query / retrieval intent / retrieval strategy / citations / latency。**不输出 chain-of-thought**（sink 前自动脱敏） |

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