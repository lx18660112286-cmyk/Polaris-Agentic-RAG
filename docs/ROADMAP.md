# Polaris Agentic RAG — Roadmap

项目分阶段演进。每一阶段必须包含：Goal、Deliverables、Non-goals、Acceptance Criteria。

## Stage 0 — Clean Bootstrap + LightRAG Source Integration

**Goal**: 干净的工程骨架 + LightRAG 以 Git Submodule + editable source 方式接入，建立依赖边界与架构地基。

**Deliverables**:
- Python 项目初始化（pyproject / src 布局 / .venv）
- Git 初始化 + LightRAG submodule + pinned commit
- LightRAG editable source install 与 path verification
- source probe（21 项必查）
- architecture boundary + AST guard
- configuration skeleton（应用层 + Adapter 层）
- example knowledge base（4 份内部一致的虚拟系统文档）
- docs（README / ARCHITECTURE / ROADMAP / LIGHTRAG_SOURCE_INTEGRATION / ADR）
- smoke tests + quality gates（pytest / ruff / format / mypy）
- 初始 git commit

**Non-goals**:
- 不实现 RagSearchTool / KnowledgeSearchPort / LightRAGAdapter 业务逻辑
- 不实现 Retrieval Router / RetrievalPlan / Evidence Contract
- 不实现 Agent / Orchestrator / Tool Calling Loop
- 不执行真实 ingest / query / LLM / Embedding / Rerank

**Acceptance Criteria**:
- `lightrag.__file__` 解析到 `third_party/LightRAG`
- 生产代码 LightRAG import 只存在于 `adapters/lightrag/`
- 无 LightRAG 类型向上泄漏
- pytest / ruff / format / mypy 全绿；smoke tests 通过；零网络调用

## Stage 1 — LightRAG Native E2E Baseline

**Goal**: 真正验证 pinned LightRAG Kernel 能稳定提供什么。

**Deliverables**:
- 真实受控 LLM provider（如 DeepSeek / Ollama）
- 真实受控 Embedding provider
- Storage lifecycle（initialize_storages / finalize_storages）
- ingest example knowledge base
- native query（query / aquery / query_data / aquery_data）
- query mode 对比（local / global / hybrid / naive / mix）
- references / citation 数据
- structured retrieval data（aquery_data 结构）
- unknown-question 与 insufficient-evidence 行为记录
- baseline evaluation cases

**Non-goals**:
- 不 Agent 化；不进入 Tool 层实现

**Acceptance Criteria**:
- 每个 query mode 在例知识库上跑通并记录结果
- 明确记录 Kernel 的 failure 行为（raise vs status field）
- 形成 Stage 2 设计 Evidence Contract 的观察依据

## Stage 2 — RagSearchTool + KnowledgeSearchPort + Evidence Contract

**状态**: ✅ 已交付（2026-09-15），详见 `docs/STAGE2_RAG_SEARCH_TOOL.md` 与 `docs/adr/0002-evidence-contract-and-search-port.md`。

**Goal（关键阶段）**: 把 Kernel 包装成稳定的 Agent-facing Tool。

**Deliverables**:
- `RagSearchTool`
- `KnowledgeSearchPort`
- `LightRAGAdapter`（正式业务实现）
- Evidence Contract（query / retrieval intent / evidence / citation / insufficient evidence / tool failure / normalized search result）
- `SourceResolver`（basename → 路径还原，三态）
- Result Mapper（raw `aquery_data` → 领域模型）
- domain exceptions（`evidence/errors.py`）
- `bootstrap.py` 组合根
- workspace 隔离（AdapterSettings.workspace）
- 真实 Kernel E2E 集成测试（唯一 workspace）

```text
Test / Caller
    ↓
RagSearchTool
    ↓
KnowledgeSearchPort
    ↓
LightRAGAdapter
    ↓
LightRAG
```

**Non-goals**:
- 不实现 Query Router / RetrievalPlan
- 不引入 Agent

**Acceptance Criteria**（已通过 `tests/architecture` + 单元测试 + 真实 E2E 验证）:
- Tool 只依赖端口，不依赖 LightRAG
- 关闭代码路径上无 LightRAG 类型泄漏
- Evidence Contract 覆盖 Stage 1 观察到的所有返回值形态
- 真实 Kernel E2E（唯一 workspace）跑通：initialize → ingest → tool.invoke → 结构化证据/citation → close

## Stage 3 — Retrieval Strategy + Query Router

**Goal**: Agent 无需知道 Kernel-specific 参数。

**状态**: ✅ 已交付（2026-09-15），详见 `docs/STAGE3_RETRIEVAL_ROUTER.md` 与 `docs/adr/0003-retrieval-routing.md`。

**Deliverables**:
- `RetrievalStrategy` / `RetrievalIntent` / `RetrievalPlan` / `RoutingDecision`（`retrieval/models.py`）
- `QueryRouter`（确定性规则，`retrieval/router.py` + `retrieval/rules.py`）
- `KnowledgeSearchPort.search(query, *, plan=None)` 演进
- `LightRAGAdapter` 内 `_STRATEGY_TO_MODE` 映射（`FOCUSED→local` 等，不向上暴露）
- `RagSearchTool` 注入 Router；`RagSearchResult.routing` 透出 `RoutingDecision`
- 移除公共契约 `RetrievalDiagnostics.query_mode`
- routing fixtures + unit tests + real routed E2E
- 架构 guard 扩展（`retrieval/` 禁 import lightrag/adapters/tools/agent）

```text
query
 ↓
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
LightRAG
```

**Acceptance Criteria**（已通过）:
- `local/global/hybrid/naive/mix` 等真实 mode 由 Router 内部决定，只在 Adapter 内
- Agent 只需要 `query`
- 确定性、可解释、可离线测试；GENERAL 走显式 fallback（`fallback_used` 可观测）
- 真实 routed E2E：factual→FOCUSED、multi-document→HYBRID 均拿到 evidence + citation
- 质量门禁：pytest 全绿、ruff check/format 全绿、mypy 全绿、architecture guard 通过

## Stage 4 — Single Agent Orchestrator

**Goal**: 单 Agent 编排，Agent 自主决定是否调用知识检索 Tool。

**状态**: ✅ 已交付（2026-09-15），详见 `docs/STAGE4_SINGLE_AGENT.md` 与 `docs/adr/0004-single-agent-tool-calling.md`。

**Deliverables**:
- `AgentOrchestrator`（原生 Tool Calling 状态机，几十行，不引入 Agent 框架）
- `AgentModelPort`（`protocols/agent_model.py`，provider-neutral）
- `DeepSeekAgentModelAdapter`（`adapters/agent_model/`，唯一 import `openai` 的地方）
- `AgentTool` + `ToolRegistry`（register / dedup / unknown / argument validation）
- `AgentRagSearchTool`（薄 wrapper，复用 Stage 2/3 `RagSearchTool`，不破坏其 contract）
- `agent/models.py`（`AgentMessage / AgentToolCall / AgentModelResponse / AgentResult / ToolCallRecord`）
- `agent/prompts.py`（tool-selection / grounding / citation / failure policy）
- `agent/errors.py` + 终止防护（`max_steps` / `max_tool_calls` / 重复调用拒绝）
- 组合根 `bootstrap.build_agent`（返回 `BuiltAgent`）+ CLI `scripts/run_agent.py`
- 架构 guard（Agent 层 + openai 仅限 agent_model 边界）
- 离线单测 + 真实 Agent E2E（direct / tool / insufficient-knowledge）

```text
User
 ↓
AgentOrchestrator (tool_choice="auto")
 ↓
ToolRegistry
 ↓
RagSearchTool
 ↓
QueryRouter
 ↓
RetrievalPlan
 ↓
KnowledgeSearchPort
```

**Acceptance Criteria**（已通过）:
- Agent 能根据任务判断调用/不调用检索工具（tool_choice="auto" 真实验证）
- 含 insufficient evidence 与 tool failure 的处理路径（不幻觉）
- Agent 只输 `query`；永不控制 `mode/top_k/rerank`
- Agent 核心不依赖 provider SDK（openai 仅限 `adapters/agent_model/`）
- 质量门禁：pytest 全绿、ruff、mypy、architecture guard 通过

## Stage 5 — Evaluation + Observability

**状态**: ✅ 已交付（2026-09-15），详见 `docs/STAGE5_EVALUATION_OBSERVABILITY.md`、`docs/STAGE5_EVALUATION_REPORT.md`
与 `docs/adr/0005-evaluation-and-observability.md`。

**Goal**: 可度量、可观测。

**Deliverables**:
- `observability/`：`Trace / TraceEvent / TraceEventType / FailureCategory`（`models.py`）、
  `Tracer`（ContextVar 传播 trace_id + 自动脱敏，`tracer.py`）、`TraceSink / InMemoryTraceSink /
  JsonlTraceSink`（`sinks.py`）、只读分析 `analysis.py`
- `evaluation/`：`EvalCase / EvalCaseResult / EvalRunResult / MetricSummary`（`models.py`）、
  确定性指标 `metrics.py`（混淆矩阵 / source recall / citation grounded / 弃答 / 延迟 / token）、
  `evaluator.py`（AgentResult + trace → 每维判定）、`EvaluationRunner`（`runner.py`）
- 埋点：`AgentOrchestrator`（AGENT/MODEL/TOOL/ERROR）、`RagSearchTool`（ROUTER/RETRIEVAL）；
  `AgentResult.trace_id`；模型 usage 透传（TokenUsage）
- 评估数据集 `examples/evaluation/dev_knowledge_eval.jsonl`（37 例 / 9 类）
- CLI：`scripts/run_evaluation.py [--limit N]`、`scripts/run_agent.py --debug`
- 架构 guard 扩展（evaluation/observability 禁 import lightrag/adapters/provider SDK）
- 离线单测（metrics / tracer / sinks / trace order / failure）+ 真实 E2E
  `tests/integration/test_evaluation_e2e.py`
- 真实评估运行与报告 `docs/STAGE5_EVALUATION_REPORT.md`（明细在 `.local/eval/eval-*.json`）

```text
AgentOrchestrator ──[Tracer: ContextVar trace_id]──▶ TraceSink ──▶ InMemory / Jsonl (.local/traces/)
RagSearchTool ────  ROUTER_DECISION / RETRIEVAL events
   │
   ▼
EvalCase.jsonl ──▶ EvaluationRunner(run_case=真实组合 Agent) ──▶ EvalCaseResult ──▶ MetricSummary
```

**Acceptance Criteria**（已通过）:
- 工具选择 / 路由意图 / 路由策略 / source recall / citation grounded / 答案术语 / 诚实弃答 /
  延迟 / token 全部有确定性指标，结果可在 `.local/eval/` 复现
- 一次请求单个 `trace_id` 贯穿 Agent → Tool → Router → Adapter；sink 前自动脱敏
- `NO_EVIDENCE` 与系统错误在失败分类中分离，评估不把业务结果当错误
- 质量门禁：pytest（离线全绿 + 真实 E2E）、ruff、mypy、architecture guard 通过

## Stage 5.1 — Evaluation Stabilization

**状态**: ✅ 已交付（2026-09-16），详见 `docs/STAGE5_1_EVALUATION_STABILIZATION.md`。
本阶段**不增加新能力**，修正 Stage 5 真实评估暴露的四类问题并完成三层归因。

**Goal**: 评估稳定化 —— 取消 routing last-write-wins、分离 Router 自身 vs Agent 改写链路、
使 rewrite drift 可观测、明确 Retrieval Invocation mismatch。

**Deliverables**:
- `RoutingStep`（`retrieval/models.py`）：step_index / tool_call_id / original_user_query /
  tool_query / intent / strategy / reason / fallback_used，一次请求多次路由全部保留
- Primary Routing Decision：`EvalCaseResult` Layer C 取**首个** routing step，后续查询不覆盖
- 三层度量拆分：Layer A Retrieval Invocation / Layer B Router Component（原始 query 直连，不经 Agent）/
  Layer C Agentic Retrieval（primary step），移除混合 `routing_accuracy`
- Query Provenance：`original_user_query` 不可变 + `tool_query` 记录，trace 用 `tool_call_id` 关联
- `critical_terms` 数据集标注 + `critical_term_preservation_rate` + `query_rewrite_drift`
- `FailureCategory` 新增 `QUERY_REWRITE_INTENT_DRIFT` / `EVALUATION_AGGREGATION_ERROR`
- prompt 改写保留策略（不强制逐字复述，禁止语义丢失；无 per-query hardcode）
- 真实 37 例重跑 + before/after 报告（`STAGE5_1_EVALUATION_STABILIZATION.md`）

```text
Dataset Query
 ├─ Layer B:  ──▶ QueryRouter.route() ──▶ 期望对照（不经 Agent / Tool / 改写）
 └─ Layer C:  ──▶ Agent ──▶ tool_query ──▶ QueryRouter ──▶ primary RoutingStep（首决策）
```

**Acceptance Criteria**（已通过，见 `docs/STAGE5_1_EVALUATION_STABILIZATION.md` §8）:
- routing steps 不再互相覆盖；primary=首决策；Router Component 与 Agentic Retrieval 分离归因
- 37 例不变（仅加 metadata）；无 per-query hardcode；Citation/Abstention 无回归
- 真实重跑：Retrieval Invocation 97.3%（FN 2→1）、primary intent/strategy 89.7%/93.1%、drift 3、
  critical-term 保留 96.7%、0 系统失败、p50/p95 3.45s/5.40s
- 质量门禁：188 离线 + 6 集成全绿，ruff / mypy 通过；LightRAG submodule 02dcd8d 不变

## Stage 5.2 — Data Flywheel

**状态**: ✅ 已交付（2026-09-16），详见 `docs/STAGE5_2_DATA_FLYWHEEL.md` 与 `docs/adr/0006-data-flywheel.md`。

**Goal**: 把真实运行时 query / 反馈 / 失败转成**人工审核、可审计、可复现、回归门禁**的改进闭环，
作为**旁路能力**（Runtime Path ≠ Learning Path，故障不影响问答）；**绝对禁止自动修改系统**
（不改 Prompt / Router / Knowledge Base）。

**Deliverables**:
- `flywheel/` 包：`models.py`（FeedbackType / ReviewCandidate / FailureLayer / ImprovementProposal /
  EvalCandidate / RegressionCheckResult / FlywheelMetrics）、`repository.py`、`sanitizer.py`、
  `review_queue.py`、`candidate_generator.py`（确定性规则 A-E）、`proposals.py`、
  `eval_promotion.py`、`regression.py`（hard_tolerance=0.01）、`metrics.py`、`service.py`（`DataFlywheelService`）
- 正确模式：`feedback → capture → classify → review → proposal → regression → human approval → apply separately`
- 复用 Trace / AgentResult / EvalCase 契约（spec §44/§45）；`FeedbackSanitizer` 基础 secret redaction，禁 CoT
- 落盘 gitignored：`.local/feedback/`、`.local/review/`、`.local/flywheel/`
- CLI：`submit_feedback.py` / `review_feedback.py` / `flywheel_report.py` / `promote_eval_case.py` +
  `_flywheel_cli.py`；`run_agent.py --feedback`
- 架构 guard 扩展（`flywheel/` 禁 import lightrag/adapters/provider SDK）
- 单测 + 集成 `tests/integration/test_data_flywheel_e2e.py`

```text
FeedbackEvent -> ReviewCandidate -> Human Review -> ImprovementProposal
   (绑定 trace_id)      (规则 A-E)     (mandatory gate)
        -> EvalCandidate -> Regression Result -> Human Decision
          (人工显式提升)     (hard_tolerance=0.01)
```

**Acceptance Criteria**（已通过离线部分，见 `docs/STAGE5_2_DATA_FLYWHEEL.md` §13）:
- 旁路：运行时未改；飞轮故障不影响问答；不自动改 Prompt/Router/KB
- `KNOWLEDGE_GAP` 一等类别；`FailureLayer` 把 rewrite drift 归 `QUERY_REWRITE` 而非 `ROUTER`
- 251 离线 + ruff + mypy 全绿；完整飞轮集成 E2E 循环通过
- 集成 4/7：3 例因 4 份文档小知识库检索覆盖波动偶发失败（已如实记录，不改 backend/断言）；
  LLM 运行时指向 `code2.rayinai.com/v1` + `deepseek-v4.1-flash`
- LightRAG submodule 02dcd8d 不变

## Project Status — Feature Complete

当前 **Scope Freeze**。项目已完成核心产品交付，不再新增产品能力。

```text
Stage 0  ✅  Clean Bootstrap + LightRAG Source Integration
Stage 1  ✅  Native LightRAG E2E Baseline
Stage 2  ✅  RagSearchTool + Evidence Contract + LightRAGAdapter
Stage 3  ✅  Retrieval Strategy + Query Router
Stage 4  ✅  Single Agent Orchestrator
Stage 5  ✅  Evaluation + Observability
Stage 5.1 ✅  Evaluation Stabilization
Stage 5.2 ✅  Data Flywheel（旁路学习路径，人工门禁）

Project Status:  FEATURE COMPLETE  →  FEATURE FREEZE
```

> 原「Stage 6 — External Tools（GitTool / LogTool / DatabaseTool / WebTool）」**不再作为正式实施计划**
> （spec：Final Stage §2）。项目最终定位是：
>
> ```text
> A production-style Agentic RAG reference project built on LightRAG as the retrieval kernel.
> ```
>
> 它既不是 Developer General Agent，也不是 Multi-Tool Agent Platform。

## Project Complete 验收（Final Stage 计划 §34）

- [x] 无新增产品功能（Scope Freeze）
- [x] README 最终版（重写为项目入口）
- [x] `docs/PROJECT_SUMMARY.md`（面试导向技术总结）
- [x] `docs/INTERVIEW_GUIDE.md`（作者面试准备）
- [x] Roadmap 止于 Stage 5.2
- [x] 架构文档一致（ARCHITECTURE / README / ADR）
- [x] Demo Flow 已文档化（4 组 query + --debug）
- [x] 可复现性已验证（clone → venv → editable install → .env → Ollama bge-m3 → tests → agent → eval）
- [x] Known Limitations 如实记录（不隐藏失败 case）
- [x] 真实评估结果原样保留（Activity baseline，37 例）
- [x] 无 benchmark gaming
- [x] 质量门禁全绿（pytest / ruff check / ruff format / mypy / integration）
- [x] integration tests 全绿
- [x] LightRAG submodule 不变（`02dcd8df754ec312b807bdd4d67737b97bc38679`）
- [x] 仓库 clean（`.local/` `.env` traces 不提交）
- [x] 最终 commit + `v1.0.0` release tag

## Optional Future Work（Not implemented by design）

以下均为**当前项目范围之外**的可选后续方向，**不构成 Roadmap 承诺**：

| 方向 | 说明 | 备注 |
|---|---|---|
| Reranker evaluation | 引入 reranker 评估其对检索质量的影响 | 需要真实 rerank provider |
| Alternative RAG kernel | 用其他 RAG 内核替换 LightRAG | 验证 Port/Adapter 隔离是否可替换供应商 |
| MCP exposure | 将 `RagSearchTool` 暴露为 MCP server | Agentic 能力外部化 |
| External developer tools | GitTool / LogTool / DatabaseTool / WebTool | 原 Stage 6，不在当前交付 |
| Production deployment | Docker / 服务化 / 鉴权 / 多租户 | 依赖运维基建 |
| Larger knowledge base | 更大规模知识库与批量评估回归 | 需要更多文档与评估用例 |

全部标注 **Not implemented by design.**