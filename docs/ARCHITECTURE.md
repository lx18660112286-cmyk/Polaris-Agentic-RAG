# Dev Knowledge Agent — Architecture

> Agentic RAG Application，面向开发者知识场景。
> 核心产品抽象是 `RagSearchTool`（Agent-facing knowledge retrieval capability），
> LightRAG 只是其背后的 RAG Kernel。

## 产品视角（Agent 看到的世界）

```text
User
 ↓
Agent
 ↓
Tool Registry
 ↓
RagSearchTool
 ↓
Knowledge Retrieval
```

Agent 只面向 Tool。Agent 理想情况下只需要提供 `query`，例如：

```python
await rag_search_tool.invoke(query="Order Service 部署失败后应该如何回滚？")
```

## 工程视角（内部实现层次）

```text
Agent Orchestrator
        ↓
   Tool Registry
        ↓
   RagSearchTool
        ↓
 Retrieval Strategy
        ↓
KnowledgeSearchPort
        ↓
 LightRAGAdapter
        ↓
 LightRAG Kernel
```

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
KnowledgeSearchPort
      ▲
      │  implements
      │
LightRAGAdapter
      │
      ▼
LightRAG
```

- 生产代码中只有 `src/dev_knowledge_agent/adapters/lightrag/` 允许 import LightRAG（由 `tests/architecture/test_boundaries.py` 用 AST 强制）。
- 禁止从 Adapter 向上 re-export `LightRAG` / `QueryParam`。
- 禁止 Tool API 接收 LightRAG-specific 类型。

## Tool 不应暴露 Kernel 参数

未来 Agent 不应直接控制：

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

检索参数由 `Query Router / Retrieval Strategy` 内部决定。

## 未来 Retrieval Plan（Stage 3 目标，Stage 0 不实现）

```text
User Query
   ↓
RagSearchTool
   ↓
Query Router
   ↓
RetrievalPlan
   ↓
KnowledgeSearchPort
   ↓
LightRAGAdapter
```

未来的内部领域模型可能类似：

```text
RetrievalPlan
- strategy
- top_k
- rerank
```

## 旁路能力

```text
Evaluation     — 检索/回答/引用评估（Stage 5）
Observability  — 日志、指标（Stage 5）
Tracing        — Tool 调用链路、router 决策（Stage 5）
```

## 本项目负责 vs LightRAG 负责

本项目负责（Agentic 层）：
- Agent-facing `RagSearchTool`
- Tool Registry
- `KnowledgeSearchPort`
- `LightRAGAdapter`
- Evidence Contract
- Retrieval Strategy / Query Router
- Agent Orchestrator
- Evaluation / Observability
- External Tools（Git / Log / Database / Web，Stage 6）

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

Stage 0 只建立这些能力未来存在的位置和边界，不实现业务逻辑。