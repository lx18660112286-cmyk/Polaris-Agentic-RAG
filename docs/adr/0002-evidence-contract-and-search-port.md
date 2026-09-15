# ADR 0002 — Evidence Contract + KnowledgeSearchPort 作为检索边界

- **Status**: Accepted
- **Date**: 2026-09-15
- **Relates to**: ADR 0001

## Context

ADR 0001 决定把 `RagSearchTool`（Agent-facing 能力）、`LightRAGAdapter`（基础设施边界）、
`LightRAG`（Kernel）分为三层。Stage 1 baseline 用真实运行证明：pinned Kernel 的
`aquery_data` 返回结构化的嵌套 dict（entities / relationships / chunks / references +
metadata.processing_info），并且：

- `file_path` 被 Kernel 归一化为 **basename**（`api_auth.md`），无法直接还原完整路径；
- naive 模式下 entities/relationships **空洞**是合法返回；
- failure 形态多样（异常 raise 或 `status="failure"`）。

如果 Agent / Tool 直接消费 Kernel 的嵌套 dict，会带来：
1. **vendor coupling**：业务与 Tool API 被绑定到 LightRAG 返回值结构；
2. **语义不稳定**：basename、空数组、截断计数、failure status 等含义要靠一层一层猜；
3. **不可测试**：Tool 无法用 fake 替换 Kernel；
4. **不可替换**：未来切换 RAG Kernel 时所有消费方都要改。

需要决定：如何在 Tool 与 Kernel 之间建立一个稳定的、框架无关的契约，以及谁来还原 basename。

## Decision

**在 Tool 与 Adapter 之间建立 `KnowledgeSearchPort`（端口），并用应用层自有的领域模型
（Evidence Contract，`evidence/models.py`）作为交换类型。**

```text
RagSearchTool  -- 依赖 -->  KnowledgeSearchPort (Protocol)
                                 ▲
                                 │ implements
                              LightRAGAdapter -- 直连 --> LightRAG
```

关键判断：

1. **`KnowledgeSearchPort` 只暴露一个方法** `async search(query: str) -> KnowledgeSearchResult`。
   `KnowledgeSearchResult` 是框架无关的 Pydantic 模型，**不携带任何 LightRAG 类型/参数**。
2. **检索参数（mode / top_k / rerank / include_references）被隔离在 Adapter 内部**
   （`LightRAGAdapterSettings` + `_build_query_param()`），Agent/Tool 不可见、不可传。
   这保证 Stage 3 的 Query Router 能安全地接管策略，而不改变 Tool API。
3. **Evidence Contract 定义在本项目**，字段形状扎根于 Stage 1 真实 payload；
   raw 字段缺失时保持 `None`，不伪造值。
4. **`SourceResolver` 负责 basename → 路径还原**，三态结果（`RESOLVED / UNRESOLVED / AMBIGUOUS`），
   歧义绝不静默选一个。这是 Adapter 内部职责，不泄漏到 Tool。
5. **异常归一化边界**：Adapter 把 LightRAG 的各类异常（`EmptyQueryError`、`ValueError: Unknown mode`、
   `TypeError(NoneType)`、`status="failure"`）压成本项目领域异常（`evidence/errors.py`），
   保证 Tool/Agent 只见统一的失败语义。
6. **工具语义是"检索"而非"最终作答"**：`RagSearchTool` 返回 `evidence + citations + diagnostics`，
   `EvidenceAvailability.NONE → status=NO_EVIDENCE`，把"证据不足"显式化，而不是透传空值。

## Alternatives Considered

### Option A — Tool 直接消费 Kernel 的 raw dict

**拒绝。** 理由见 Context：vendor coupling、语义不稳定、不可测试、不可替换。

### Option B — Tool 返回 Kernel 的 aquery 文本 + 引用文件列表

**拒绝。** 既丢了结构化证据（entities/relationships/chunk），也不能表达证据充分性/截断信号，
Background Agent 无法可信地合成答案或做 citation 校验。

### Option C — Evidence Contract 直接照搬 Kernel 结构（foreign-key 语义）

**部分采纳但降级**：我们把 Kernel 的**字段**作为映射来源，但**结构归我们所有**
（chunk→`ChunkEvidence`、reference→`Citation`、processing_info→`RetrievalDiagnostics`），
不把 `data.entities[...]` 这类嵌套 dict 直接上抛。

### Option D — Adapter 内部自己造证据（SourceResolver 静默补全 basename）

**拒绝**，关键点：`SourceResolver` 只有在 `RESOLVED`（唯一命中）时才填 `source_path`；
`UNRESOLVED` / `AMBIGUOUS` 都保持 `None` 并记录状态，绝不静默选择一个文件。

## Consequences

正面影响：
- Tool/Agent 与 Kernel 彻底解耦：可替换第二个 RAG Kernel、可 fake 测试、可加 observability；
- 检索参数收敛在 Adapter，为 Stage 3 Router 留出干净接管点；
- 引用可还原完整路径（评论/inspection/跳转），且歧义被显式暴露；
- 失败语义统一，Agent 能可靠判断是否 insufficient evidence / tool failure。

代价：
- 维护一层端口 + 领域模型 + mapper 的映射成本；
- 需要持续跟踪 pinned Kernel 的 `aquery_data` 结构（submodule 固定 commit 缓解，回退即重跑 mapper 测试）；
- `SourceResolver` 依赖 knowledge roots 配置，若 roots 配置错了会导致引用解析失真（需测覆盖）。

## When To Revisit

- 引入第二个 RAG Kernel 时（此时 Evidence Contract 是稳定的跨内核交换格式，应保持不变）。
- Kernel 升级改变 `aquery_data` 结构或去重语义时（新增 ADR 记录映射差异而非悄悄改模型）。
- 引入 Query Router / RetrievalPlan（Stage 3）后，若需要把 `mode/top_k` 从 Adapter 提升为
  可配置策略参数，需在此 ADR 上增加修订，说明策略参数的边界。