# Polaris Agentic RAG — Architecture

> **Agentic RAG Application**，面向开发者知识场景，构建在 **LightRAG** 检索内核之上。
> 核心产品抽象是 `RagSearchTool`（Agentic RAG knowledge retrieval capability boundary）。
> 系统动态决定是否检索、规划检索、把 Kernel 输出归一化为应用自有 Evidence Contract，再做
> grounded synthesis 或 abstention。

## 产品视角（用户看到的世界）

```text
User Query
 ↓
Agentic RAG Orchestrator
 ↓
RagSearchTool
 ↓
Knowledge Retrieval
```

Agentic RAG Orchestrator（Stage 4 已实现）通过原生 function calling 动态判定「是否需要检索」
（Retrieval Invocation）并执行 grounded synthesis。用户只需提供 `query`：

```python
await agent.run("Order Service 部署失败后应该如何回滚？")
```

> `ToolRegistry` 仅是 native function calling runtime 的**内部执行机制**（注册、校验、调用
> `RagSearchTool`），不是产品概念；本项目不以多 Tool orchestration 为目标。

## 工程视角（内部实现层次）

```text
User Query
        ↓
 Agentic RAG Orchestrator
        ↓            （Retrieval Invocation: 要不要检索）
   RagSearchTool
        ↓
   QueryRouter
        ↓            （Retrieval Planning: 怎么检索）
   RetrievalPlan
        ↓
KnowledgeSearchPort
        ↓
 LightRAGAdapter
        ↓
 LightRAG Kernel
```

`ToolRegistry` 在 runtime 内部负责 native function calling 的注册与调用分发，不进入上图主链语义。

## 返回方向（数据流回程）

```text
LightRAG
   ↓
Adapter
   ↓
Evidence / Search Result
   ↓
RagSearchTool
   ↓
Agent
   ↓
Final Answer
```

## 三个层级的定位（不要混用）

| 层 | 定位 | 面向 |
|---|---|---|
| `RagSearchTool` | Agent-facing abstraction | 领域能力：query / intent / evidence / citation / insufficient evidence / tool failure / normalized search result |
| `LightRAGAdapter` | Infrastructure abstraction | LightRAG-specific：QueryParam / aquery / mode / top_k / rerank / storage lifecycle / exceptions |
| `LightRAG` | RAG Kernel | 文档插入、chunk、entity/relation 抽取、图与向量索引、检索、上下文构建、storage 抽象、embedding/LLM/rerank 集成、references |

**RagSearchTool 是 Agent 能力；LightRAGAdapter 是基础设施边界；LightRAG 是底层 Kernel。三者不是同一层。**

## 依赖边界（不可违反）

```text
RagSearchTool
      │
      ▼
QueryRouter
      │
      ▼
RetrievalPlan
      │
      ▼
KnowledgeSearchPort
      ▲
      │  implements
      │
LightRAGAdapter
      │
      ▼
LightRAG
```

- 生产代码中只有 `src/polaris_agentic_rag/adapters/lightrag/` 允许 import LightRAG（由 `tests/architecture/test_boundaries.py` 用 AST 强制）。
- 禁止从 Adapter 向上 re-export `LightRAG` / `QueryParam`。
- 禁止 Tool API 接收 LightRAG-specific 类型。
- **Stage 2 / Stage 3 已落地**：`KnowledgeSearchPort` 暴露 `async search(query, *, plan=None) -> KnowledgeSearchResult`；
  `plan` 是应用自有 `RetrievalPlan`；`KnowledgeSearchResult` 是框架无关领域模型（`evidence/models.py`）。
- Tool 只依赖 Port + Router，不依赖 Adapter（由架构测试强制 `tools/` 不得 import `adapters/`）。
- **Retrieval 映射只在 Adapter**：`RetrievalStrategy → LightRAG mode`（`_STRATEGY_TO_MODE`）藏于
  `adapters/lightrag/`。Router / Tool / protocols 不触碰真实 `mode`。

## Retrieval（Stage 3 已实现）

`retrieval/` 是应用策略层（框架无关，不含 vendor 类型）：

```text
query
  ↓
QueryRouter.route(query)
  ↓
RetrievalPlan { intent, strategy, top_k, chunk_top_k, enable_rerank, reason }
  ↓
KnowledgeSearchPort.search(query, plan)
```

- `RetrievalStrategy ∈ {FOCUSED, GLOBAL, HYBRID, VECTOR, MIXED}`（应用自有）
- `RetrievalIntent ∈ {FACTUAL, TERMINOLOGY, RELATIONAL, MULTI_DOCUMENT, OVERVIEW, GENERAL}`
- `QueryRouter` 用**确定性规则**（`retrieval/rules.py`），无网络 / 无 LLM / 离线可测。
- 回退显式：意外失败 → 安全 hybrid plan + `RoutingDecision.fallback_used=True`（透出在 `RagSearchResult.routing`）。

## Evidence Contract（Stage 2 已实现）

`evidence/models.py` 定义框架无关的检索证据模型：

```text
KnowledgeSearchResult
 ├─ query
 ├─ evidence        { chunks / entities / relationships }
 ├─ citations       [ {reference_id, source_name, source_path, source_resolution} ]
 ├─ diagnostics     { keywords / counts / processing_info(...) }
 └─ evidence_availability ∈ {NONE, PRESENT, TRUNCATED}
```

- 字段形状扎根于 pinned Kernel `aquery_data` 的真实返回；缺失字段保持 `None`，不伪造。
- Kernel 只给 citation 的 **basename** → Adapter 内部用 `SourceResolver` 还原完整路径，
  三态结果（`RESOLVED / UNRESOLVED / AMBIGUOUS`），歧义绝不静默选择。
- Kernel/Adapter 的各种失败被 `evidence/errors.py` 归一化为统一领域异常（Tool/Agent 只见统一失败语义）。
- **Stage 3 移除** `RetrievalDiagnostics.query_mode`：真实 LightRAG `mode` 只在 Adapter 内部，
  应用层用 `RetrievalPlan.strategy` / `RetrievalIntent`。

## Agentic RAG Orchestration（Stage 4 已实现）

Agentic RAG 编排层（`agent/`），负责 **Retrieval Invocation** 与 **Grounded Synthesis**：

```text
User Query
 ↓
AgentOrchestrator  (native function calling, tool_choice="auto")
 ↓
AgentRagSearchTool  (薄 wrapper, 复用 Stage 2/3 RagSearchTool；内部经 ToolRegistry 调用)
```

- **Retrieval Invocation**：`AgentModelPort`（framework-agnostic）让 LLM 决定"直接回答 还是 调
  `search_dev_knowledge`"——用 provider 原生 function calling，不自制 ACTION 文本协议。
  这是 **Agentic RAG orchestration decision**，不是 multi-tool selection。
- `DeepSeekAgentModelAdapter`（`adapters/agent_model/`）是唯一 import `openai` 的地方；编排核心
  不依赖 provider SDK。
- **Retrieval Planning**：仍由 Stage 3 `QueryRouter` 决定"怎么检索"。Orchestrator 永不接触
  `mode/top_k/rerank`。
- **Grounded Synthesis / Abstention**：只在有证据时综合答案并引用，证据不足时诚实弃答。
- `AgentResult / ToolCallRecord / AgentStatus`：供调用方消费与 observability。
- 终止防护：`max_steps` / `max_tool_calls` / 重复调用拒绝；错误归一化不外泄 SDK 异常。

> `ToolRegistry`（`tools/registry.py`）是 native function calling runtime 的内部执行机制，
> 用于注册、校验和调用 `RagSearchTool`；本项目以单个知识能力为目标，不以多 Tool orchestration 为目标。

## workspace 隔离（Stage 2 新增）

LightRAG 的 `doc_status` 去重与 store 按 `workspace` 命名空间划分，与 `working_dir` 解耦。
`LightRAGAdapterSettings.workspace`（默认跟随全局 `WORKSPACE` env）用于为不同知识库/环境
隔离去重与存储；留空即共享全局。详情见 `docs/STAGE2_RAG_SEARCH_TOOL.md` §6。

## Tool 不应暴露 Kernel 参数（Stage 3 已落实）

Agent 不应直接控制：

```text
mode
top_k
chunk_top_k
enable_rerank
QueryParam
```

Agent 理想情况下只需要 `query`：

```python
rag_search(query="...")
```

检索参数已由 `QueryRouter` 内部决定并产出 `RetrievalPlan`（Stage 3）。

## 旁路能力

```text
Evaluation     — 检索/回答/引用评估（Stage 5，已实现）
Observability  — 结构化 trace / 失败分类 / 延迟与 token（Stage 5，已实现）
Tracing        — Agent -> Tool -> Router -> Adapter 整链 trace_id 关联（Stage 5，已实现）
Data Flywheel  — 反馈→审查→提案→回归→人工决策 的旁路学习路径（Stage 5.2，已实现）
```

### Observability / Evaluation（Stage 5 已实现）

```text
AgentOrchestrator ──[Tracer: ContextVar trace_id]──▶ TraceSink ──▶ InMemory / Jsonl (.local/traces/)
RagSearchTool ────  ROUTER_DECISION / RETRIEVAL events
   │
   ▼
EvalCase.jsonl ──▶ EvaluationRunner(run_case=真实组合 Agent) ──▶ EvalCaseResult ──▶ MetricSummary
   └───────── EvalCaseResult.events(确定性指标: 工具选择混淆矩阵 / source recall / citation grounded / 弃答)
```

- `observability/`：应用自有 `TraceEventType` / `FailureCategory` 契约；Tracer 用 ContextVar 低侵入传播
  `trace_id`；事件在到达 sink 前自动脱敏（secret / chain-of-thought）。`evaluation/` 与
  `observability/` 均不 import LightRAG / provider SDK（架构 guard 强制）。
- `NO_EVIDENCE`（诚实弃答）与系统失败（MODEL_ERROR / TOOL_ERROR / MAX_STEPS…）在 `FailureCategory`
  中明确分离，评估汇总不会把正常业务结果当错误。
- 评估指标全部确定性（混淆矩阵 / 集合 recall / 术语包含），无 LLM 裁判；运行结果落盘
  `.local/eval/eval-*.json` 可复现。详见 `docs/STAGE5_EVALUATION_OBSERVABILITY.md`、`docs/STAGE5_EVALUATION_REPORT.md`
  与 `ADR 0005`。

### Evaluation 三层归因（Stage 5.1 新增）

Stage 5 的单一 routing 混合指标在 Stage 5.1 拆为三层（spec §2/§21），禁止再把
"QueryRouter 本身是否分类正确" 与 "Agent → tool_query → QueryRouter 整链是否正确" 混为一谈：

```text
Dataset Query
 ├─ Layer B Router Component:  original query ──▶ QueryRouter.route() ──▶ 期望对照
 │                                           （不经 Agent / Tool Calling / LLM rewrite）
 └─ Layer C Agentic Retrieval:  user query ──▶ Agent ──▶ tool_query ──▶ QueryRouter
                                                              └─▶ primary RoutingStep（首决策）
```

- `RoutingStep`（`retrieval/models.py`）保存一次请求的**全部**路由步骤
  （`step_index / tool_call_id / original_user_query / tool_query / intent / strategy / reason /
  fallback_used`）；**Primary Routing Decision = 首个 routing step**，取消 last-write-wins
  （spec §6-§7）。
- Query Provenance 由 `AgentOrchestrator` 保存：`original_user_query` 不可变，`tool_query` 是实际
  发给 `search_dev_knowledge` 的查询（spec §9）；`RagSearchTool.search(query)` 契约不变（spec §10）。
- Trace 事件用 `tool_call_id` 关联（`TOOL_CALL_STARTED / TOOL_CALL_COMPLETED / ROUTER_DECISION`），
  不依赖事件列表位置（spec §20）。
- 改写诊断：`critical_term_preservation_rate`（人工标注实体/错误码/约束保留率）+ `query_rewrite_drift`
  （改写丢术语 或 intent flip）→ 归因 `QUERY_REWRITE_INTENT_DRIFT`，不再误归因为 Router 失败
  （spec §12-§14/§18）。`FailureCategory` 另含 `EVALUATION_AGGREGATION_ERROR`（修复后真实运行应为 0）。
- prompt 改写策略：保留 retrieval intent / 命名实体 / 错误码 / 数值约束 / 操作动作 / 问题范围，
  允许合理改写、禁止语义丢失（spec §11）。详见 `docs/STAGE5_1_EVALUATION_STABILIZATION.md`。

### Data Flywheel（Stage 5.2 新增，旁路学习路径）

Runtime Path（正常问答）与 Learning Path（飞轮）**彻底解耦**——飞轮故障不影响问答，且
**绝对禁止自动修改系统**（不改 Prompt / Router / Knowledge Base）：

```text
FeedbackEvent -> ReviewCandidate -> Human Review -> ImprovementProposal
   (绑定 trace_id)      (规则 A-E)     (mandatory gate)
        -> EvalCandidate -> Regression Result -> Human Decision
          (人工显式提升)     (hard_tolerance=0.01)
```

- `flywheel/` 是纯数据状态机（`DataFlywheelService`），只 capture / queue / review / propose /
  promote / run-regression；知识更新必须由人来落地（spec §35/§75）。
- 模型层面复用既有契约：`AgentResult` / `Trace` / `EvalCase` / `MetricSummary`（spec §44/§45）。
- `KNOWLEDGE_GAP` 是一等问题类型；层式失败归因（`FailureLayer`）把 rewrite drift 归
  `QUERY_REWRITE` 而非 `ROUTER`；候选分类走确定性规则（spec §47），无 LLM 裁判。
- 落盘 gitignored：`.local/feedback/`、`.local/review/`、`.local/flywheel/`；
  `FeedbackSanitizer` 做基础 secret redaction，禁止保存 CoT（spec §42）。
- CLI：`submit_feedback.py` / `review_feedback.py` / `flywheel_report.py` /
  `promote_eval_case.py`；`run_agent.py --feedback` 交互打分。
  详见 `docs/STAGE5_2_DATA_FLYWHEEL.md` 与 `ADR 0006`。

## 本项目负责 vs LightRAG 负责

本项目负责（Agentic RAG 应用层）：
- Retrieval Invocation（是否检索）
- Retrieval Planning（怎么检索）— Query Router / RetrievalPlan
- Agent-facing `RagSearchTool`
- `KnowledgeSearchPort`
- `LightRAGAdapter`
- Evidence Contract
- Grounded synthesis / abstention
- Evaluation / Observability

LightRAG 负责（Kernel 能力）：
- 文档插入与处理
- chunk 管理
- entity / relation extraction
- graph indexing / vector indexing
- retrieval 与 query modes
- context construction
- storage abstraction
- embedding / LLM / rerank 集成
- references / citation 相关数据

## 最重要的一句话

```text
如何把 RAG Kernel（LightRAG）转化为 Agent 可以可靠使用的 Tool（RagSearchTool）。
```

Stage 0 建立这些能力的位置与边界；Stage 1 用真实运行验证了 pinned Kernel 的 E2E 行为
（见 `docs/STAGE1_LIGHTRAG_BASELINE.md`）；Stage 2 落地 `RagSearchTool / KnowledgeSearchPort /
Evidence Contract / LightRAGAdapter`（见 `docs/STAGE2_RAG_SEARCH_TOOL.md` 与 `ADR 0002`）；
Stage 3 落地确定性 `QueryRouter → RetrievalPlan` 与 `retrieval/` 策略层（见
`docs/STAGE3_RETRIEVAL_ROUTER.md` 与 `ADR 0003`）；Stage 4 实现 `Single Agent`（原生 Tool
Calling + `AgentOrchestrator`），Agent 已不再是 roadmap 中的未来概念（见 `docs/STAGE4_SINGLE_AGENT.md`
与 `ADR 0004`）。