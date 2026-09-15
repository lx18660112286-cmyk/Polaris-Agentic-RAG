# ADR 0001 — LightRAG as an External RAG Kernel

- **Status**: Accepted
- **Date**: 2026-09-15

## Context

Dev Knowledge Agent 是一个面向开发者知识场景的 Agentic RAG Application。

整个项目的核心产品抽象是 Agent-facing 的知识检索能力 `RagSearchTool`，而不是某个具体 RAG 框架。Agent 未来只感知 Tool / query / evidence / citation，不应感知 `LightRAG`、`QueryParam`、`local/global/hybrid`、`top_k` 等 Kernel 特定概念。

项目需求需要稳定可靠的 RAG 内核（解析、分块、向量、图、混合检索、rerank、上下文构建），同时保留：
- source-level 学习与调试能力；
- 对检索元数据 / references / structured retrieval data 的可探测性；
- 为后续 Evaluation、Observability、Agent Orchestrator 提供干净边界；
- 面试演示能力（能讲清楚每一层在做什么）。

因此需要决定：LightRAG 在项目中的角色与项目自身的分层。

## Decision

- **LightRAG is treated as an external RAG Kernel.**
- **The Agent does not depend on LightRAG directly.**
- **Agent-facing retrieval capability will be exposed through `RagSearchTool`.**
- **`RagSearchTool` depends on an application-level search abstraction**（`KnowledgeSearchPort`）。
- **LightRAG-specific behavior is isolated inside `src/dev_knowledge_agent/adapters/lightrag/`.**

最终依赖方向：

```text
Agent Orchestrator
      ↓
  Tool Registry
      ↓
  RagSearchTool
      ↓
  KnowledgeSearchPort
      ↑  implements
      ↓
  LightRAGAdapter
      ↓
  LightRAG Kernel
```

关键架构判断：

| 层 | 定位 |
|---|---|
| `RagSearchTool` | Agent-facing abstraction（领域能力：query / intent / evidence / citation / failure） |
| `LightRAGAdapter` | Infrastructure abstraction（LightRAG-facing） |
| `LightRAG` | RAG Kernel（底层实现） |

三者不是同一层，不得混用。

### 集成方式（Source SDK）

当前选择：**LightRAG Python Core + Git Submodule + Editable Install**，而不是 REST API Server。

理由：
- 可直接阅读源码，理解真实检索行为（entity/relation/chunk 如何被组织）；
- 可观测 `aquery_data` 等 structured retrieval data 的真实结构；
- 调试与接口探索成本低，便于设计稳定 Adapter；
- 便于 Agentic RAG Evaluation 与面试演示。

需要明确：这是**有意识的工程 trade-off**，不代表 Source Core 一定比 REST 更适合生产环境。未来生产部署可能重新评估 REST Server（见 `docs/LIGHTRAG_SOURCE_INTEGRATION.md`）。

## Alternatives Considered

### Option A — Agent 直接调用 LightRAG

```python
rag.aquery("...", param=QueryParam(mode="hybrid", top_k=20))
```

**拒绝。** 理由：
- vendor coupling：业务层被绑定到 LightRAG 类型；
- LightRAG 参数（mode / top_k / rerank）泄漏进 Agent 层；
- 难以测试（无法替换内核）；
- 难以替换其他 RAG Kernel；
- 没有 Tool 抽象，Agent 无法统一编排多个能力。

### Option B — 极薄 @tool 装饰器包一层

```python
@tool
async def rag_search(query):
    return await rag.aquery(query, ...)
```

**不作为最终架构。** 理由：
- Tool 与 Kernel 强耦合；
- retrieval strategy 泄漏（mode/top_k 由谁决定不清晰）；
- 缺 Evidence Contract（返回什么结构不确定）；
- 缺 failure model（查询失败如何表达不确定）；
- observability 边界模糊；
- 后续多 Tool、多策略扩展困难。

### Option C — RagSearchTool → Application abstraction → LightRAG Adapter → LightRAG Kernel

**采用。** 即本 ADR 的 Decision。

### Option D — 自研完整 RAG Engine

**拒绝。** 理由：本项目目标是 Agentic Application Engineering，不是重写 Parser/Chunker/Vector/Graph/Hybrid/Rerank。除非有明确证据证明 LightRAG 无法满足需求，否则禁止自研 KDAG Kernel 已有能力。

## Consequences

正面影响：
- Agent / Tools 层与内核解耦，可测试、可替换；
- LightRAG 参数与类型被隔离在 Adapter 内，Vendor Type 不向上泄漏；
- Evidence / citation / failure 语义由应用层定义，而不是由 LightRAG 返回值决定；
- 未来 Evaluation / Tracing 有清晰挂载点。

代价：
- 多一层抽象，需要维护端口与 Adapter 之间的映射；
- 需要持续跟踪 pinned LightRAG 的 API 演进（submodule 固定 commit 缓解）；
- 集成成本高于直接调用（但远低于自研内核）。

## When To Revisit

- LightRAG 无法满足某个检索需求，需要直接 patch 其源码时（必须先新建 ADR，说明问题、为何 Adapter 无法解决、是否 fork、submodule 策略、upstream 贡献策略）。
- 项目部署形态转向生产长期运行，需要重新评估 REST Server 集成时。
- 需要替换/增加第二个 RAG Kernel 时。