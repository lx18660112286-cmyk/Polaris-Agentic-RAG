# Dev Knowledge Agent

**Dev Knowledge Agent** is an Agentic RAG application that uses **LightRAG** as its
retrieval kernel.

Instead of exposing LightRAG directly to the Agent, the project introduces a stable,
framework-agnostic contract between the two:

```text
RagSearchTool
KnowledgeSearchPort
LightRAGAdapter
Evidence Contract
Retrieval Router
Agent Orchestrator
Evaluation
Observability
```

一句话定位：

```text
把 RAG Kernel（LightRAG）转化为 Agent 可以可靠使用的 Tool（RagSearchTool）。
```

项目最终定位是 **production-style Agentic RAG reference project**，不是
Developer General Agent，也不是 Multi-Tool Agent Platform。当前状态 `FEATURE COMPLETE`（Scope Freeze）。

> 项目状态：**FEATURE COMPLETE**（Stage 0–5.1 全部交付，不再新增产品能力）。各阶段见
> [docs/ROADMAP.md](docs/ROADMAP.md)。

---

## What This Project Is

面向开发者知识场景（部署文档、鉴权、事故排查 Runbook 等）的 Agentic RAG 应用。
Agent 通过一次 `query`，自主决定是否检索知识、如何检索、如何基于证据给出带引用的回答。

## Why Agentic RAG

传统的「一次检索一次回答」不够：实际开发问题往往需要 Agent 判断

- **要不要检索**（能否直接回答？还是必须先查内部运营知识？）
- **怎么检索**（是取事实、抓术语定义、找多文档关联，还是回顾系统全貌？）

Agentic RAG 把这两个判断交给系统，而不是写死在 `@tool -> LightRAG.aquery()` 里。

## Architecture

```text
                  User
                   │
                   ▼
           AgentOrchestrator
                   │
            Tool Calling
                   │
                   ▼
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
                   │
                   ▼
          LightRAGAdapter
                   │
                   ▼
          LightRAG Kernel

                   │
          ┌────────┴────────┐
          ▼                 ▼
     Evaluation        Observability
```

### 两个决策，必须区分（spec §9）

| 决策 | 问题 | 负责者 |
|---|---|---|
| **Agent Decision** | *Should knowledge retrieval be used?*（要不要检索） | Agent Tool Calling |
| **Retrieval Decision** | *How should knowledge be retrieved?*（怎么检索） | QueryRouter |

**禁止将两者统称 `Router` 而不区分**。Agent Decision 由 LLM 原生 Tool Calling 回答；
Retrieval Decision 由确定性规则 `QueryRouter` 回答。

### 三个层级，不要混用

| 层 | 定位 | 面向 |
|---|---|---|
| `RagSearchTool` | Agent-facing abstraction | 领域能力：query / intent / evidence / citation / insufficient evidence / tool failure / normalized search result |
| `LightRAGAdapter` | Infrastructure boundary | LightRAG-specific：QueryParam / mode / top_k / rerank / storage lifecycle |
| `LightRAG` | RAG Kernel | 文档插入、chunk、entity/relation 抽取、图与向量索引、检索、上下文构建、storage、references |

## Request Flow

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

- 生产代码中只有 `src/dev_knowledge_agent/adapters/lightrag/` 允许 import LightRAG（AST 架构守卫强制）。
- 禁止从 Adapter 向上 re-export `LightRAG` / `QueryParam`；Tool API 不接收 LightRAG-specific 类型。
- `KnowledgeSearchPort.search(query, *, plan=None)` 是框架无关领域模型；`RetrievalStrategy → LightRAG mode`
  的映射只藏在 Adapter 内。

## Why LightRAG

LightRAG 负责其原生能力：文档插入/处理、chunk、entity/relation 抽取、图与向量索引、检索与
query modes、上下文构建、storage 抽象、embedding/LLM/rerank 集成、references。

项目**不重复实现**这些能力：Parser / Chunker / Embedding Pipeline / Vector Store / BM25 /
Graph Retrieval / Hybrid Retrieval / Reranker / Context Builder / 普通 RAG Pipeline 全部禁止自研。

## Why RagSearchTool

Agent 面向领域能力，不是框架 API：

```python
# Agent 这样调用
await rag_search_tool.invoke(query="Order Service 部署失败后应该如何回滚？")

# 而不是这样
rag.aquery("...", param=QueryParam(mode="hybrid", top_k=20))
```

Agent 不需要知道 `QueryParam`、`local/global/hybrid`、`top_k`、`enable_rerank`。

## Why Evidence Contract

`evidence/models.py` 定义框架无关的检索证据模型，形状扎根于 pinned Kernel `aquery_data`
真实返回，缺失字段保持 `None` 不伪造：

```text
KnowledgeSearchResult
 ├─ query
 ├─ evidence        { chunks / entities / relationships }
 ├─ citations       [ {reference_id, source_name, source_path, source_resolution} ]
 ├─ diagnostics     { keywords / counts / processing_info(...) }
 └─ evidence_availability ∈ {NONE, PRESENT, TRUNCATED}
```

- Kernel 只给 citation 的 **basename** → Adapter 用 `SourceResolver` 还原完整路径（三态：
  `RESOLVED / UNRESOLVED / AMBIGUOUS`，歧义绝不静默选择）。
- Kernel / Adapter 的各种失败被归一化为统一领域异常，Tool / Agent 只见统一失败语义。

## Retrieval Routing

`retrieval/` 是应用策略层（框架无关，无 vendor 类型）：

```text
query
  ↓
QueryRouter.route(query)        # 确定性规则，无网络 / 无 LLM / 离线可测
  ↓
RetrievalPlan { intent, strategy, top_k, chunk_top_k, enable_rerank, reason }
  ↓
KnowledgeSearchPort.search(query, plan)
```

- `RetrievalStrategy ∈ {FOCUSED, GLOBAL, HYBRID, VECTOR, MIXED}`
- `RetrievalIntent ∈ {FACTUAL, TERMINOLOGY, RELATIONAL, MULTI_DOCUMENT, OVERVIEW, GENERAL}`
- 路由优先级（确定性，`retrieval/rules.py`）：
  `OVERVIEW > TERMINOLOGY > RELATIONAL > MULTI_DOCUMENT > FACTUAL > GENERAL`
- 回退显式：意外失败 → 安全 hybrid plan + `RoutingDecision.fallback_used=True`（透出在 `RagSearchResult.routing`）。

## Agent Tool Calling

`agent/` 是 Single Agent 编排层（原生 Tool Calling 状态机，几十行，不引入 Agent 框架）：

```text
User
 ↓
AgentOrchestrator  (native tool calling loop, tool_choice="auto")
 ↓
ToolRegistry
 ↓
AgentRagSearchTool  (薄 wrapper, 复用 Stage 2/3 RagSearchTool)
```

- **Layer 1（Agent）**：`AgentModelPort` 让 LLM 决定"直接回答 还是 调 `search_dev_knowledge`"，
  用 provider 原生 Tool Calling，不自制 ACTION 文本协议。
- `DeepSeekAgentModelAdapter` 是唯一 import `openai` 的地方；Agent 核心不依赖 provider SDK。
- **Layer 2（RAG）**：仍由 `QueryRouter` 决定"怎么检索"。Agent 永不接触 `mode/top_k/rerank`。
- 终止防护：`max_steps` / `max_tool_calls` / 重复调用拒绝；错误归一化不外泄 SDK 异常。

## Evaluation

评估**分层**而非只给最终答案打分（spec §12/§15）：

```text
Dataset Query
 ├─ Layer B Router Component:  original query ──▶ QueryRouter.route() ──▶ 期望对照
 │                                            （不经 Agent / Tool Calling / LLM rewrite）
 └─ Layer C Agentic Retrieval:  user query ──▶ Agent ──▶ tool_query ──▶ QueryRouter
                                                                └─▶ primary RoutingStep（首决策）
```

- **Layer A — Tool Selection**：Agent 是否调用工具（accuracy / precision / recall / FP / FN）。
- **Layer B — Router Component**：原始 query 直连 Router，Router 自身分类是否准确。
- **Layer C — Agentic Retrieval**：Agent 改写后的 `tool_query` 经 Router 后的**首次**决策。
- 指标全部确定性（混淆矩阵 / 集合 recall / 术语包含），**无 LLM 裁判**；运行结果落盘 `.local/eval/eval-*.json`。
- Query Provenance：`original_user_query` 不可变 + `tool_query` 记录 + 事件用 `tool_call_id` 关联。

详见 [docs/STAGE5_EVALUATION_OBSERVABILITY.md](docs/STAGE5_EVALUATION_OBSERVABILITY.md) 与
[docs/STAGE5_1_EVALUATION_STABILIZATION.md](docs/STAGE5_1_EVALUATION_STABILIZATION.md)。

## Key Results

**37 evaluation cases**（9 类，`examples/evaluation/dev_knowledge_eval.jsonl`），真实 baseline：

| Metric | Value |
|---|---:|
| Tool Selection Accuracy | **97.3%** |
| Tool Selection Precision | 100.0% |
| Tool Selection Recall | 96.7% |
| Router Component Intent Accuracy | **90.0%** |
| Router Component Strategy Accuracy | **93.3%** |
| Primary Agentic Intent Accuracy | 89.7% |
| Primary Agentic Strategy Accuracy | 93.1% |
| Citation Groundedness | **100.0%** |
| Abstention Accuracy | **100.0%** |
| Expected Source Recall | 96.0% |
| Latency p50 / p95 | 3453.0 / 5401.8 ms |
| Tokens per case | 4260.7 |

> 不隐藏失败 case：FN=1（f3）、Router 规则边界 3 例、query rewrite drift 3 例，均如实记录在
> [docs/STAGE5_EVALUATION_REPORT.md](docs/STAGE5_EVALUATION_REPORT.md) 与
> [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md) 的 Known Limitations。

## Project Structure

```text
.
├── README.md
├── pyproject.toml
├── .gitignore / .gitmodules / .env.example
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   ├── PROJECT_SUMMARY.md          # 面试导向技术总结
│   ├── INTERVIEW_GUIDE.md          # 面试准备
│   ├── STAGE*.md                    # 各阶段交付说明
│   └── adr/0001..0005-*.md          # 架构决策记录
├── examples/
│   ├── knowledge_base/              # 虚拟系统文档（deployment / api_auth / incident_runbook / service_overview）
│   └── evaluation/dev_knowledge_eval.jsonl   # 37 例评估数据集
├── scripts/
│   ├── run_agent.py                 # Agent REPL 演示（--debug 打印 trace）
│   ├── run_evaluation.py            # 真实评估
│   ├── stage1_baseline.py           # Stage 1 基线
│   └── README.md
├── src/dev_knowledge_agent/
│   ├── config/                      # 应用配置
│   ├── protocols/                   # knowledge_search.py / agent_model.py（端口）
│   ├── adapters/
│   │   ├── lightrag/                # 唯一允许 import LightRAG 的包
│   │   └── agent_model/deepseek.py  # 唯一允许 import openai 的包
│   ├── retrieval/                   # QueryRouter / RetrievalPlan / RoutingStep / rules
│   ├── evidence/                    # Evidence Contract + errors
│   ├── tools/                       # RagSearchTool / AgentRagSearchTool / ToolRegistry
│   ├── agent/                       # AgentOrchestrator / models / prompts / errors
│   ├── evaluation/  observability/  # 评估与观测
│   └── bootstrap.py                 # 组合根：build_agent -> BuiltAgent
├── tests/
│   ├── architecture/test_boundaries.py   # AST 架构守卫
│   ├── unit/                              # 离线单测
│   └── integration/                       # 真实 provider E2E
└── third_party/LightRAG                  # git submodule（pin 02dcd8df...）
```

## Quick Start

按可复现顺序执行（不依赖未写进本 README 的隐含环境）：

```bash
# 1. clone（含 submodule）
git clone --recurse-submodules <repo>

# 2. 虚拟环境
python -m venv .venv
# Windows: .venv\Scripts\activate

# 3. editable 安装（LightRAG 必须来自 submodule source）
python -m pip install -e third_party/LightRAG
python -m pip install -e ".[dev]"

# 4. 配置 .env（gitignored，勿提交真实 key）
cp .env.example .env
# 在 .env 中填入 DEEPSEEK_API_KEY=...

# 5. 拉取 Ollama embedding 模型（bge-m3）
ollama pull bge-m3

# 6. 运行测试
pytest -m "not integration"

# 7. 运行 Agent
python scripts/run_agent.py [--debug]

# 8. 运行评估
python scripts/run_evaluation.py
```

> Python 3.10+（本项目用 3.12.9）。`scripts/run_agent.py` 与 `scripts/run_evaluation.py`
> 会自动从项目 `.env` 读取 `DEEPSEEK_API_KEY`（进程内已有环境变量优先）。

## Running the Agent

需要真实凭据（`.env` 中的 `DEEPSEEK_API_KEY`）与 Ollama `bge-m3` embedding：

```bash
python scripts/run_agent.py
```

```text
User> Access token 的有效期是多少？
Agent> access token 的有效期是 30 分钟。[api_auth.md]
```

## Running Evaluation

```bash
python scripts/run_evaluation.py [--limit N]
```

## Testing

```bash
pytest -m "not integration"    # 离线单测 + 架构守卫（无网络）
pytest -m integration -v       # 真实 provider E2E（需要 API key + Ollama）
```

## Quality Gates

```bash
pytest -m "not integration"
ruff check src tests scripts
ruff format --check src tests scripts
mypy src
pytest -m integration -v
```

所有命令必须通过。默认排除 `third_party/`（不 lint LightRAG upstream）。
**Final 验收：188 离线 + 6 集成全绿；ruff / mypy 通过；架构守卫通过。**

## Architecture Decisions

| ADR | 主题 |
|---|---|
| [0001](docs/adr/0001-lightrag-as-rag-kernel.md) | LightRAG is Kernel, not Agent framework |
| [0002](docs/adr/0002-evidence-contract-and-search-port.md) | Evidence Contract + KnowledgeSearchPort |
| [0003](docs/adr/0003-retrieval-routing.md) | Retrieval Routing（确定性规则） |
| [0004](docs/adr/0004-single-agent-tool-calling.md) | Single Agent Orchestrator |
| [0005](docs/adr/0005-evaluation-and-observability.md) | Evaluation + Observability |

## Known Limitations

如实记录（不隐藏失败 case，见 spec §3-§5/§10）：

1. **f3（"401 和 403 有什么区别"）Tool Selection false-negative**（FN=1）：该问题可同时理解为
   generic HTTP knowledge 与 internal authentication policy，Agent 用通用协议知识直接作答，
   事实正确但不调工具。**未对该 query hardcode**，作为已知边界保留。
2. **Router 规则边界 3 例**（t4 / r4 / m4）：确定性规则未识别 "scope" 术语、误判 "是什么关系"、
   "如何诊断" 触发 relational 倾向。记为后续可选精化项，**不做 keyword soup**。
3. **Query rewrite drift 3 例**（g2 / i1 真实改写漂移，f3 为 FN 副作用）：Agent 改写查询对
   确定性路由有用但可能改变路由特征。这是项目**已知 trade-off**；通过 Layer B/C 分层归因暴露，
   不强制 Agent verbatim copy query，不禁用改写。
4. **Kernel 内部 LLM token 不可统计**：`total_tokens` 仅统计 DeepSeek Agent 调用 usage，
   LightRAG 内部 LLM usage 无法可靠获取，不冒充系统 total。
5. **Latency 主体在 LightRAG 检索**：p95 ≈ 5.4s，主要为 local/hybrid 检索 + graph walk。

## Project Scope

当前 **Scope Freeze**（见 [docs/ROADMAP.md](docs/ROADMAP.md) 的 Optional Future Work）。

**范围外（Not implemented by design）**：MCP / GitTool / LogTool / DatabaseTool / WebTool /
Multi-Agent / Memory / LangGraph migration / 新 RAG features / reranker / production deployment /
larger knowledge base。

## Interview Highlights

- **LightRAG is Kernel, not Agent framework**：项目不依赖 LightRAG 的 Agent/Tool 能力。
- **Agent 不直接依赖 LightRAG**：只依赖 `KnowledgeSearchPort`（Port）+ `RagSearchTool`（Tool）。
- **Evaluation 分层**：Layer A Tool Selection / Layer B Router Component / Layer C Agentic Retrieval，
  避免把 Router 自身缺陷与 Agent 改写混为一谈。
- **Query Provenance + RoutingStep**：一次请求多步路由全保留，primary=首决策，改写漂移可观测。
- **确定性路由 / 确定性指标**：Router 无 LLM 可离线测；评估无 LLM 裁判，结果可在 `.local/eval/` 复现。

---

更完整的访谈准备见 [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md) 与
[docs/INTERVIEW_GUIDE.md](docs/INTERVIEW_GUIDE.md)。