# Dev Knowledge Agent

面向开发者知识场景的 **Agentic RAG Application**。核心产品抽象是
`RagSearchTool`（Agent-facing knowledge retrieval capability），
LightRAG 只是它背后的 RAG Kernel。

> 整个项目最终不是 `Agent → LightRAG`，也不是 `@tool → LightRAG.aquery()`，
> 而是：
>
> ```text
> User → AgentOrchestrator → Tool Registry → RagSearchTool → Retrieval Strategy
>      → KnowledgeSearchPort → LightRAGAdapter → LightRAG Kernel
> ```

## 1. 这是什么

一个「把 RAG Kernel 转化为 Agent 可以可靠使用的 Tool」的工程实践项目。

- **面向**：开发者知识场景（部署文档、鉴权、事故排查 Runbook 等）。
- **经典形态**：`rag_search(query="Order Service 部署失败后如何回滚？")`。

## 2. 为什么这是 Agentic RAG 项目

它不仅做「一次检索一次回答」，而是围绕 **Agent 编排多 Tool、多步骤** 展开：

- 未来 Agent 通过 Tool Registry 调用 `RagSearchTool` 等工具；
- 检索策略、证据、引用、工具失败、证据不足等语义由应用层定义；
- 旁路：Evaluation / Observability / Tracing。

各阶段见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 3. 为什么核心 Agent capability 是 RagSearchTool

Agent 面向的是**领域能力**而不是**某个框架的 API**：

```python
# Agent 这样调用（未来）
await rag_search_tool.invoke(query="Order Service 部署失败后应该如何回滚？")

# 而不是这样
rag.aquery("...", param=QueryParam(mode="hybrid", top_k=20))
```

Agent 不需要知道 `QueryParam`、`local/global/hybrid`、`top_k`、`enable_rerank`。

## 4. 为什么 LightRAG 只是 Kernel

LightRAG 负责其原生能力：文档插入/处理、chunk、entity/relation 抽取、
图与向量索引、检索与 query modes、上下文构建、storage 抽象、
embedding/LLM/rerank 集成、references 数据。

- 禁止自研：Parser / Chunker / Embedding Pipeline / Vector Store / BM25 /
  Graph Retrieval / Hybrid Retrieval / Reranker / Context Builder / 普通 RAG Pipeline。
- 唯一例外：有明确证据证明 LightRAG 无法满足需求。

## 5. LightRAG 负责什么

见上方 [4]，以及 [docs/LIGHTRAG_SOURCE_INTEGRATION.md](docs/LIGHTRAG_SOURCE_INTEGRATION.md)
的能力表格（全部来自 pinned source probe）。

## 6. 本项目负责什么

- Agent-facing `RagSearchTool`（Stage 2）
- Tool Registry（Stage 2/4）
- `KnowledgeSearchPort`（Stage 2）
- `LightRAGAdapter`（Stage 2）
- Evidence Contract（Stage 2）
- Retrieval Strategy / Query Router（Stage 3）
- Agent Orchestrator（Stage 4）
- Evaluation / Observability（Stage 5）
- External Tools：GitTool / LogTool / DatabaseTool / WebTool（Stage 6）

## 7. 本项目不做什么

- 不重复实现 LightRAG 已有能力（自研 RAG Engine）。
- 各阶段陆续实现后，以下仅作为当时的非目标（historical）：Stage 0 不实现
  RagSearchTool 业务逻辑、KnowledgeSearchPort、LightRAGAdapter、Retrieval Router、
  Evidence Contract、Agent、Tool Calling Loop、ingestion pipeline、evaluation、
  tracing、真实模型请求 —— 这些已在 Stage 2/3/4 逐阶段落地。
- Stage 4 明确不做：外部 Tools（Git/Log/DB/Web，Stage 6）、Multi-Agent、LangGraph、
  长期记忆 / 会话持久化、完整 Evaluation framework、Tracing backend、Web UI。

## 8. 当前 Stage

**Stage 4 — Single Agent Orchestrator**（当前已实现，2026-09-15）。

- Stage 0：Clean Bootstrap + LightRAG Source Integration（`third_party/LightRAG` submodule，
  pin `02dcd8df754ec312b807bdd4d67737b97bc38679`）。
- Stage 1：Native LightRAG E2E Baseline（真实 provider，记录 Kernel 行为）。
- Stage 2：`RagSearchTool` + `KnowledgeSearchPort` + Evidence Contract + `LightRAGAdapter`。
- Stage 3：`QueryRouter` + `RetrievalPlan` + Retrieval Strategy（确定性路由）。
- Stage 4：`AgentOrchestrator`（原生 Tool Calling）+ `ToolRegistry` + `DeepSeekAgentModelAdapter`。

各阶段与验收见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 9. 项目结构

```text
.
├── README.md
├── pyproject.toml
├── .gitignore
├── .gitmodules
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   ├── LIGHTRAG_SOURCE_INTEGRATION.md
│   └── adr/0001-lightrag-as-rag-kernel.md
├── examples/knowledge_base/   # 虚拟系统：deployment / api_auth / incident_runbook / service_overview
├── scripts/
│   ├── stage1_baseline.py          # Stage 1 基线
│   └── run_agent.py                # Stage 4 Agent CLI 演示
├── src/dev_knowledge_agent/
│   ├── config/settings.py          # 应用配置（含 agent_* 设置）
│   ├── protocols/
│   │   ├── knowledge_search.py     # KnowledgeSearchPort（Stage 2）
│   │   └── agent_model.py          # AgentModelPort（Stage 4）
│   ├── adapters/
│   │   ├── lightrag/               # 唯一允许 import LightRAG 的包
│   │   │   ├── settings.py / errors.py / source_probe.py
│   │   │   ├── adapter.py / mapper.py / source_resolver.py / native_baseline.py
│   │   └── agent_model/
│   │       └── deepseek.py         # 唯一允许 import openai 的包
│   ├── retrieval/                  # Stage 3：QueryRouter / RetrievalPlan / rules
│   ├── evidence/                   # Stage 2：Evidence Contract + errors
│   ├── tools/
│   │   ├── protocol.py             # AgentTool / ToolDefinition（Stage 4）
│   │   ├── registry.py             # ToolRegistry（Stage 4）
│   │   └── rag_search.py           # RagSearchTool + AgentRagSearchTool wrapper
│   ├── agent/
│   │   ├── orchestrator.py         # Agent Loop（Stage 4）
│   │   ├── models.py / prompts.py / errors.py
│   ├── bootstrap.py                # 组合根：build_agent -> BuiltAgent
│   └── evaluation/ observability/  # 未来位置（Stage 5）
├── tests/
│   ├── architecture/test_boundaries.py   # AST 架构守卫
│   ├── unit/                             # 离线单测（registry / orchestrator / router / mapper ...）
│   └── integration/                      # 真实 provider E2E（native / tool / routed / agent）
└── third_party/LightRAG                  # git submodule
```

## 10. 环境创建

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
```

需要 Python 3.10+（本次用 3.12.9）。

## 11. Git Submodule 初始化

新 clone 方式：

```bash
git clone --recurse-submodules <repo>
```

如果已经 clone 过但没有初始化 submodule：

```bash
git submodule update --init --recursive
```

> 本机 Windows 访问 GitHub 需要代理/TUN，git 建议使用 schannel 后端
> （`git config http.sslBackend schannel`，写入本地配置，不随仓库提交）。

## 12. Editable Source Install

```bash
python -m pip install -e third_party/LightRAG   # LightRAG 必须来自 submodule source
python -m pip install -e ".[dev]"               # 本项目 + dev 依赖
```

根项目不声明 `lightrag-hku` 普通 PyPI 依赖；LightRAG 必须来自
`third_party/LightRAG`。验收：

```bash
python -c "import lightrag, pathlib, os; p=pathlib.Path(lightrag.__file__).resolve(); normv=os.path.normpath(str(p)); assert 'third_party'+os.sep+'LightRAG' in normv or 'third_party/LightRAG' in normv, normv"
```

## 13. 如何运行测试

```bash
pytest -m "not integration"    # 默认排除需要联网/真实模型的 integration tests
```

`integration` marker 预留给未来需要网络、真实 LLM/Embedding/Rerank、ingest、
外部 API 的测试。Stage 0 无 integration 测试。

## 14. Quality Gates

```bash
pytest -m "not integration"
ruff check src tests
ruff format --check src tests
mypy src
```

所有命令都必须通过。范围默认排除 `third_party/`（不 lint LightRAG upstream）。

## 15. 一次真实 Agent 会话（Stage 4 演示）

需要真实凭据（`DEEPSEEK_API_KEY`）：

```bash
.\\.venv\\Scripts\\python.exe scripts/run_agent.py
```

```text
User> Access token 的有效期是多少？
Agent> access token 的有效期是 30 分钟。[api_auth.md]
```

Agent（`AgentOrchestrator`）通过原生 Tool Calling 自主决定直接回答还是调用
`search_dev_knowledge`，并基于返回的 evidence 综合答案、引用 source。

## 架构决策

为什么要这套分层？见 [docs/adr/0001-lightrag-as-rag-kernel.md](docs/adr/0001-lightrag-as-rag-kernel.md)、
[docs/adr/0002-evidence-contract-and-search-port.md](docs/adr/0002-evidence-contract-and-search-port.md)、
[docs/adr/0003-retrieval-routing.md](docs/adr/0003-retrieval-routing.md)、
[docs/adr/0004-single-agent-tool-calling.md](docs/adr/0004-single-agent-tool-calling.md)。