# Polaris Agentic RAG

**Polaris Agentic RAG is an Agentic RAG application built on top of LightRAG.**

LightRAG is treated as the **retrieval kernel** rather than exposed directly to the
orchestration layer. The system **dynamically decides whether retrieval is required**,
**plans the retrieval strategy**, **normalizes kernel output into an application-owned
Evidence Contract**, and performs **grounded answer synthesis or abstention**.

一句话定位：

> Polaris Agentic RAG is an Agentic RAG system that dynamically decides whether retrieval is
> required, plans how retrieval should be executed, normalizes LightRAG kernel output into
> structured evidence, and performs grounded synthesis or abstention with layered evaluation
> and observability.

项目核心能力是：仿照 LightRAG Kernel 构建一个具有**动态检索决策、检索规划、Evidence Contract、
grounded answer synthesis、abstention、layered evaluation 和 observability** 的 Agentic RAG 系统。

> 项目状态：**FEATURE COMPLETE**（Stage 0–5.2 全部交付，最终进入 FEATURE FREEZE）。各阶段见
> [docs/ROADMAP.md](docs/ROADMAP.md)。

---

## Overview

 Agentic RAG 应用。Agentic 的核心
不是「工具多」，而是**运行时决策**：先判断要不要检索，再规划怎么检索，最后基于证据回答或拒答。

## Why Agentic RAG

```text
Traditional RAG
Query → Fixed Retrieval → Context → LLM

Agentic RAG（本项目）
User Query → Retrieval Invocation → Retrieval Planning → Dynamic Retrieval
          → Evidence Normalization → Grounded Synthesis → Answer / Abstain
```

与传统 RAG 一次固定检索不同，本项目在检索前有两个**显式的运行时决策层**，并由证据约束最终的合成。

## Architecture

```text
                    User Query
                        │
                        ▼
             Agentic RAG Orchestrator
                        │
               Retrieval Invocation
                        │
            ┌───────────┴───────────┐
            │                       │
      No Retrieval              Retrieval
            │                       │
            │                       ▼
            │                 RagSearchTool
            │                       │
            │                       ▼
            │                  QueryRouter
            │                       │
            │                       ▼
            │                 RetrievalPlan
            │                       │
            │                       ▼
            │              KnowledgeSearchPort
            │                       │
            │                       ▼
            │                LightRAGAdapter
            │                       │
            │                       ▼
            │                 LightRAG Kernel
            │                       │
            │                       ▼
            │                    Evidence
            │                       │
            └───────────┬───────────┘
                        ▼
                Grounded Synthesis
                        │
                        ▼
                 Answer / Abstain

              Evaluation + Observability
```

### 两个 Agentic RAG 决策层（必须区分）

| 决策                                    | 问题                                                         | 负责者                                               |
| ------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------- |
| **Decision A — Retrieval Invocation** | *Does this user query require knowledge retrieval?*（要不要检索） | Agentic RAG Orchestrator（native function calling） |
| **Decision B — Retrieval Planning**   | *How should retrieval be performed?*（怎么检索）                 | QueryRouter → RetrievalPlan                       |

> Agentic RAG 将「是否需要检索（Retrieval Invocation）」与「如何检索（Retrieval Planning）」
> 拆成两个独立决策层。

## Retrieval Invocation

```text
Decision A — Should retrieval happen?
```

由 Agentic RAG Orchestrator 基于用户查询动态判定（原生 function calling，`tool_choice="auto"`）：

```text
你好                           → No Retrieval（直接回答）
Access token 的有效期是多少？  → Retrieval
```

这是 **Agentic RAG orchestration decision**，不是 multi-tool selection。项目只有
`RagSearchTool` 一个知识能力，没有多工具编排诉求。

## Retrieval Planning

```text
Decision B — How should retrieval happen?
```

若 Retrieval Invocation = true，交给确定性 `QueryRouter` 产出 `RetrievalPlan`：

```text
FACTUAL       → FOCUSED
OVERVIEW      → GLOBAL
MULTI_DOCUMENT → HYBRID
TERMINOLOGY   → FOCUSED
RELATIONAL    → HYBRID
GENERAL       → HYBRID（显式 fallback，fallback_used 可观测）
```

- 路由优先级（确定性，`retrieval/rules.py`）：`OVERVIEW > TERMINOLOGY > RELATIONAL > MULTI_DOCUMENT > FACTUAL > GENERAL`
- `QueryRouter` 无网络、无 LLM、离线可测；`RetrievalPlan` 是应用自有的策略对象。

## Evidence Contract

`evidence/models.py` 定义框架无关、应用自有的证据模型，形状扎根于 pinned Kernel `aquery_data`
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
- Kernel / Adapter 的各种失败被归一化为统一领域异常，Orchestrator 只见统一失败语义。

## Grounded Synthesis

```text
Decision C — What can be safely answered from retrieved evidence?
```

- Agent 只在有证据时综合答案；证据不足或 `evidence_availability = NONE` 时**诚实弃答**，绝不编造。
- 答案只引用返回的 citation，不给来源就不编来源（Citation Groundedness 100% 验证）。
- 层次：Orchestrator 负责最终合成，`RagSearchTool` 负责检索 —— Orchestrator 永不控制
  `mode/top_k/rerank`。

## Why LightRAG

LightRAG 是 **External RAG Kernel**，负责 document processing / chunk / entity-relationship
extraction / graph retrieval / vector retrieval / hybrid retrieval / storage / embedding / LLM
integration / references。

Agentic RAG 应用层负责 Retrieval Invocation / Retrieval Planning / Evidence Contract /
citation normalization / grounded synthesis / abstention / evaluation / observability。

项目**不重复实现** Kernel 已有能力（Parser / Chunker / Embedding Pipeline / Vector Store / BM25 /
Graph Retrieval / Hybrid Retrieval / Reranker / Context Builder）。

## Evaluation

评估**分层**，而非只给最终答案打分；全部指标**确定性**（混淆矩阵 / 集合 recall / 术语包含），
**无 LLM 裁判**，结果可在 `.local/eval/eval-*.json` 复现。

| Layer                                     | 衡量                               | 关键指标                                                                    |
| ----------------------------------------- | -------------------------------- | ----------------------------------------------------------------------- |
| **Layer A — Retrieval Invocation**        | *Should retrieval be triggered?* | Accuracy / Precision / Recall / FP / FN                                 |
| **Layer B — Retrieval Planning**          | Router 自身对原始查询分类                 | Router Intent Accuracy / Strategy Accuracy / Fallback Rate              |
| **Layer C — Agentic Retrieval Execution** | Orchestrator+改写查询经 Router 的首决策   | Primary Intent / Strategy / Rewrite Drift / Critical Term Preservation  |
| **Layer D — Retrieval / Evidence**        | 检索是否命中期望来源                       | Expected Source Recall / Evidence Availability / Citation Source Recall |
| **Layer E — Grounded Synthesis**          | 合成是否接地、是否诚实弃答                    | Answer Term Match / Citation Groundedness / Abstention Accuracy         |

> 旧的单一混合「routing accuracy」已移除；Layer B 直连 Router（不经 Agent），Layer C 走
> Authentic→改写→Router 链路，二者不再混为一谈。

## Observability

一个 `trace_id` 贯穿 Agentic RAG Orchestrator → RagSearchTool → Router → Adapter，记录
Retrieval Invocation 结果、改写前后查询、Retrieval Plan、引用、延迟、token；事件在 sink 前
自动脱敏（secret / chain-of-thought）。Query Provenance：`original_user_query` 不可变 +
`tool_query` 记录 + 事件用 `tool_call_id` 关联。

## Data Flywheel

真实运行时 query / 反馈 / 失败转入**人工审核、可审计、可复现、回归门禁**的改进闭环，
作为**旁路能力**（Runtime ≠ Learning，故障不影响问答），且**绝对禁止自动修改系统**：

```text
FeedbackEvent -> ReviewCandidate -> Human Review -> ImprovementProposal
   (绑定 trace_id)      (规则 A-E)     (mandatory gate)
        -> EvalCandidate -> Regression Result -> Human Decision
          (人工显式提升)     (hard_tolerance=0.01)
```

- `feedback → capture → classify → review → proposal → regression → human approval → apply separately`；
  不自动改 Prompt / Router / Knowledge Base。
- `KNOWLEDGE_GAP` 一等类别；`FailureLayer` 把 rewrite drift 归 `QUERY_REWRITE` 而非 `ROUTER`；
  候选分类确定性规则，无 LLM 裁判；复用 Trace / AgentResult / EvalCase 契约。
- 落盘 gitignored（`.local/feedback/`、`.local/review/`、`.local/flywheel/`）；
  `FeedbackSanitizer` 基础 secret redaction，禁止保存 CoT。
- CLI：`submit_feedback.py` / `review_feedback.py` / `flywheel_report.py` / `promote_eval_case.py`；
  `run_agent.py --feedback` 交互打分。详见 [docs/STAGE5_2_DATA_FLYWHEEL.md](docs/STAGE5_2_DATA_FLYWHEEL.md)。

## Key Results

**37 evaluation cases**（9 类，`examples/evaluation/dev_knowledge_eval.jsonl`），真实 baseline：

| Metric                            | Value              |
| --------------------------------- | ------------------:|
| Retrieval Invocation Accuracy     | **97.3%**          |
| Retrieval Invocation Precision    | 100.0%             |
| Retrieval Invocation Recall       | 96.7%（FP=0, FN=1）  |
| Router Intent Accuracy            | **90.0%**          |
| Router Strategy Accuracy          | **93.3%**          |
| Primary Agentic Intent / Strategy | 89.7% / 93.1%      |
| Citation Groundedness             | **100.0%**         |
| Abstention Accuracy               | **100.0%**         |
| Expected Source Recall            | 96.0%              |
| Latency p50 / p95                 | 3453.0 / 5401.8 ms |
| Tokens per case                   | 4260.7             |

> 不隐藏失败 case：FN=1（f3）、Router 规则边界 3 例、query rewrite drift 3 例，均如实记录在
> [docs/STAGE5_EVALUATION_REPORT.md](docs/STAGE5_EVALUATION_REPORT.md) 与
> [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md) 的 Known Limitations。

## Demo

基于现有 `scripts/run_agent.py`，不新增功能：

| Demo                                             | 期望展示                                                                                                                           |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| **1**：`你好`                                       | **Retrieval Invocation = false**（0 次检索，直接回答）                                                                                   |
| **2**：`Access token 的有效期是多少？`                    | **Retrieval Invocation = true** → FACTUAL → FOCUSED → `[api_auth.md]` → grounded answer                                        |
| **3**：`Order Service 发布后出现大量 5xx，应该如何排查并判断是否回滚？` | Retrieval → MULTI_DOCUMENT → 多来源 → grounded synthesis                                                                          |
| **4**：`Billing Service 使用什么数据库？`                 | Retrieval → **insufficient evidence → abstain**（拒绝幻觉）                                                                          |
| **--debug**                                      | 展示 `trace_id` / retrieval invocation / tool query / retrieval intent / strategy / citations / latency。**不输出 chain-of-thought** |

## Quick Start

按可复现顺序执行（不依赖隐含环境）：

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

> Python 3.10+（本项目用 3.12.9）。两个脚本都会自动从项目 `.env` 读取 `DEEPSEEK_API_KEY`
> （进程内已有环境变量优先）。

## Project Structure

```text
.
├── README.md
├── pyproject.toml / .gitignore / .gitmodules / .env.example
├── docs/
│   ├── ARCHITECTURE.md / ROADMAP.md
│   ├── PROJECT_SUMMARY.md / INTERVIEW_GUIDE.md
│   ├── STAGE*.md / adr/0001..0006-*.md
├── examples/
│   ├── knowledge_base/            # deployment / api_auth / incident_runbook / service_overview
│   └── evaluation/dev_knowledge_eval.jsonl   # 37 例评估数据集
├── scripts/  run_agent.py / run_evaluation.py / stage1_baseline.py
│             submit_feedback.py / review_feedback.py / flywheel_report.py / promote_eval_case.py
│             _flywheel_cli.py
├── src/polaris_agentic_rag/
│   ├── config/  protocols/         # knowledge_search.py / agent_model.py（端口）
│   ├── adapters/  lightrag/（唯一 import LightRAG）/ agent_model/deepseek.py（唯一 import openai）
│   ├── retrieval/  evidence/  tools/  agent/
│   ├── evaluation/  observability/  flywheel/
│   └── bootstrap.py               # 组合根：build_agent -> BuiltAgent
├── tests/  architecture / unit / integration
└── third_party/LightRAG            # git submodule（pin 02dcd8df...）
```

> 注：`ToolRegistry`（`tools/registry.py`）是 native function calling runtime 的**内部执行机制**，
> 用于注册、校验和调用 `RagSearchTool`；本项目不以多 Tool orchestration 为目标。

## Architecture Decisions

| ADR                                                        | 主题                                      |
| ---------------------------------------------------------- | --------------------------------------- |
| [0001](docs/adr/0001-lightrag-as-rag-kernel.md)            | LightRAG is Kernel, not Agent framework |
| [0002](docs/adr/0002-evidence-contract-and-search-port.md) | Evidence Contract + KnowledgeSearchPort |
| [0003](docs/adr/0003-retrieval-routing.md)                 | Retrieval Routing（确定性规则）                |
| [0004](docs/adr/0004-single-agent-tool-calling.md)         | Single Tool Calling Orchestrator        |
| [0005](docs/adr/0005-evaluation-and-observability.md)      | Evaluation + Observability              |
| [0006](docs/adr/0006-data-flywheel.md)                     | Data Flywheel（旁路学习路径）                   |

## Known Limitations

如实记录（不隐藏失败 case）：

1. **f3（"401 和 403 有什么区别"）Retrieval Invocation 边界**（FN=1）：可同时理解为 generic HTTP
   knowledge 与 internal authentication knowledge，Agent 用通用知识直接作答、事实正确但不触发检索。
   **未对该 query hardcode**。
2. **Router 规则边界 3 例**（t4 / r4 / m4）："scope" 未识别为术语、"…是什么关系" 误判 terminology、
   "如何诊断" 触发 relational 倾向。记为可选精化项，**不做 keyword soup**。
3. **Query rewrite drift 3 例**（g2 / i1 真实漂移，f3 为 FN 副作用）：Agent 改写查询可能改变确定性
   路由特征（intent flip）。经 Layer B/C 分层归因暴露，不强制 verbatim copy，不禁用改写。
4. **Kernel 内部 LLM token 不可统计**：`total_tokens` 仅统计 Orchestrator 调用的 DeepSeek usage。
5. **Latency 主体在 LightRAG 检索**（p95 ≈ 5.4s）。
6. 小知识库、有限 37 例评估集、确定性 Router 规则边界、reranker 未评估、评估非大规模统计、
   provider/model 行为可能变化。
7. **数据集飞轮为旁路 + 人工门禁**：不改运行时间系统。运行时 LLM 指向网关
   `https://code2.rayinai.com/v1` + `deepseek-v4.1-flash`（`.env` 配置）。离线 251 + ruff + mypy 全绿；
   集成 4/7，其中 3 例（`test_agent_e2e` / flywheel 引用断言 / `test_lightrag_native_e2e`）因
   **4 份文档小知识库的检索覆盖波动**偶发失败（实体/关键词抽取每次非确定 → 命中 source 子集不同），
   完整飞轮 E2E 循环已验证通过；此波动如实记录，不改 backend / 不改测试断言。

## Project Scope

当前 **Scope Freeze**（见 [docs/ROADMAP.md](docs/ROADMAP.md) 的 Optional Future Work）。

**范围外（Not part of the current Agentic RAG scope）**：multi-tool / external developer tools
（Git/Log/DB/Web）/ Multi-Agent / Memory / LangGraph migration / 新 RAG features / reranker /
alternative kernel / production deployment / MCP exposure / larger knowledge base。

---

完整的访谈准备见 [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md) 与
[docs/INTERVIEW_GUIDE.md](docs/INTERVIEW_GUIDE.md)。
