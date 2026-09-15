# Dev Knowledge Agent — Roadmap

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

**Deliverables**:
- `Query Router`（根据 query 意图决定 strategy）
- `RetrievalPlan`（strategy / top_k / rerank）

```text
query
 ↓
Query Router
 ↓
RetrievalPlan
 ↓
RagSearchTool / Search Port
```

**Acceptance Criteria**:
- `local/global/hybrid/mix` 等模式由 Router 内部决定
- Agent 只需要 `query`

## Stage 4 — Single Agent Orchestrator

**Goal**: 单 Agent 编排，Agent 自主决定是否调用知识检索 Tool。

**Deliverables**:
- Agent / Planner
- Tool Registry（注册 RagSearchTool 等）
- Tool Calling Loop 最小闭环

```text
Agent
 ↓
Tool Registry
 ↓
RagSearchTool
```

**Acceptance Criteria**:
- Agent 能根据任务判断调用/不调用检索工具
- 含 insufficient evidence 与 tool failure 的处理路径

## Stage 5 — Evaluation + Observability

**Goal**: 可度量、可观测。

**Deliverables**:
- retrieval evaluation（mode 对比、top_k 对比）
- answer evaluation
- citation evaluation
- tool-call tracing
- latency / token usage / failure category
- router decision trace

## Stage 6 — External Tools

**Goal**: 形成真正的 Multi-Tool Developer Agent。

**Deliverables**:
- GitTool
- LogTool
- DatabaseTool
- WebTool

```text
                 ┌─ RagSearchTool
                 │
Agent ─ ToolRegistry ─ GitTool
                 │
                 ├─ LogTool
                 │
                 ├─ DatabaseTool
                 │
                 └─ WebTool
```

**Acceptance Criteria**:
- 多 Tool 场景下 Agent 能编排不同工具解决真实开发者任务