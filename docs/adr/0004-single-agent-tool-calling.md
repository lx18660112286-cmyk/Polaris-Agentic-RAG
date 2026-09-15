# ADR 0004 — Single Agent Tool Calling（原生 Tool Calling + 框架无关 Orchestrator）

- **Status**: Accepted
- **Date**: 2026-09-15
- **Relates to**: ADR 0001（LightRAG as Kernel）、ADR 0002（Evidence Contract / Search Port）、ADR 0003（Retrieval Routing）

## Context

Stage 3 之后系统是稳定的检索链：

```text
RagSearchTool -> QueryRouter -> RetrievalPlan -> KnowledgeSearchPort -> LightRAGAdapter -> LightRAG
```

但还没有"决策层"：谁来判断一个用户问题是否需要检索、谁负责把 evidence 综合成自然语言答案。
Stage 4 要新增 Single Agent。

核心问题与约束：
- Agent 必须能选择 **直接回答** 或 **调用 `RagSearchTool`**（工具选择），且只能向模型暴露 `query`。
- Agent **永远不能**知道 / 控制 `mode / top_k / rerank`（那是 Stage 3 QueryRouter 的职责，两层 Routing 必须分开）。
- Agent LLM 与 LightRAG 内部 LLM 是两个架构角色，Agent 核心不得 import `lightrag.llm.*`。
- 必须用 provider 原生 Tool Calling，不能自制 `ACTION:` 文本协议。
- 保持最小闭环、可离线单测（FakeModel / FakeTool）。

## Decision

采用：**原生 provider Tool Calling + 框架无关的 `AgentOrchestrator`**（几十行状态机，不引入 Agent 框架）。

```text
User
 ↓
AgentOrchestrator (native tool calling loop)
 ↓
ToolRegistry
 ↓
AgentRagSearchTool  (薄 wrapper, 复用 Stage 2/3 RagSearchTool)
 ↓
(编排器只依赖)
    protocols.agent_model.AgentModelPort  <- DeepSeekAgentModelAdapter implements
    tools.registry.ToolRegistry
```

关键判断：

1. **两层 Routing 分离**：
   - Layer 1（Stage 4）：`AgentOrchestrator` 决定 *要不要调工具*（tool_choice="auto"，由 LLM 自主选择）。
   - Layer 2（Stage 3）：`RagSearchTool -> QueryRouter` 决定 *怎么检索*。
   - Agent 永不接触 retrieval mode。
2. **`AgentModelPort`**（`protocols/agent_model.py`）：provider-neutral 的模型接口
   `async complete(messages, tools) -> AgentModelResponse`。Agent 核心只依赖它，不依赖 OpenAI/DeepSeek SDK。
3. **`DeepSeekAgentModelAdapter`**（`adapters/agent_model/deepseek.py`）：唯一允许 import
   `openai` 的地方。负责 domain types ↔ provider wire types 的双向转换；错误被归一化为
   `DeepSeekAgentModelError`，不向上泄漏 SDK 形状。
4. **Agent 领域模型**（`agent/models.py`）：`AgentMessage / AgentToolCall / AgentModelResponse /
   AgentResult / ToolCallRecord / AgentStatus`。`openai.types.chat.*` 不透出。
5. **`AgentTool` + `ToolRegistry`**（`tools/`）：通用工具抽象与注册表；registry 只管理应用 Tools，
   不依赖模型 provider / LightRAG。重复注册 → `DuplicateToolError`；未知工具 → `UnknownToolError`；
   参数必须经 JSON parse → input schema 校验 → invoke，失败 → `InvalidToolArgumentsError`。
6. **薄 wrapper** `AgentRagSearchTool`（spec §15）：把 `RagSearchTool` 适配到 `AgentTool`，
   不重写、不破坏 Stage 2/3 的 Tool contract。
7. **`RagSearchInput` 生成 tool schema**（spec §35）：`ToolDefinition.parameters` 直接引用 Pydantic
   模型，provider adapter 用 `model_json_schema()` 生成，不复制两份 schema。
8. **终止与防护**：`agent_max_steps`（默认 4）与 `agent_max_tool_calls`（默认 3）双上限；
   重复的完全相同 tool call（name+arguments）被拒绝；所有工具错误进入 tool message 反馈给模型，
   不外泄 traceback。
9. **Grounding / Citation / Failure 策略** 写入 system prompt（`agent/prompts.py`）：内部事实必须基于
   evidence、必须引用 source、NO_EVIDENCE/ERROR 不得编造、不得暴露 kernel detail。
10. **组合根**（`bootstrap.py`）知道所有具体实现；`AgentOrchestrator` 本身不知道。

## Alternatives Considered

### Option A — hard-coded if/else 判断是否调 RAG

```python
if internal_question(query):
    use_rag = True
```

**拒绝作为 Agent 主路径。** 无法泛化、把"工具选择"写死，也无法区分直接回答 vs 检索；
更重要的是 spec §3 明确禁止用这种确定性 Tool Router 冒充 Agent 能力。

### Option B — LLM 输出自定义 ACTION JSON / 文本协议

```text
ACTION: search_dev_knowledge
INPUT: {...}
```

**拒绝。** 自定义 parser / schema 脆弱、不可靠，且 spec §5 明确要求用 provider 原生 Tool
Calling；自制协议会丢失 `tool_call_id` 等原生关联能力。

### Option C — 原生 provider Tool Calling + 框架无关 AgentOrchestrator

**采用。** 几十行清晰状态机即可真实证明对 `messages / tool schema / tool_calls / tool_call_id /
tool result / loop termination` 的理解，且 provider-agnostic、可离线单测。

### Option D — 立即引入 LangGraph / CrewAI 等框架

**暂不采用。** 当前一个 Tool、一个 Agent，框架复杂度 > 收益（spec §51）。如未来需要 workflow
/ 多 Agent / checkpoint，再评估 binding，不改变本次原生 loop。

## Consequences

正面影响：
- "工具选择"由**模型**（tool_choice="auto"）决定，真实反映 LLM Agent 行为；
- Agent 层与 provider 解耦（`AgentModelPort`），可替换模型 / 可 fake 测试；
- 检索参数边界清晰（Agent 只见 `query`）；
- 失败/终止语义统一（AgentStatus + ToolCallRecord），为 Stage 5 evaluation / observability 挂点。

代价：
- 多一个 AgentModelPort + provider adapter 转换层；
- 原生 tool calling 的 wire 格式可能随 provider SDK 演进（submodule/openai 版本固定缓解）；
- LLM 的 tool 选择不总稳定，真实 E2E 断言需用语义关键点而非常整文本。

## When To Revisit

- 引入第二个模型 provider 时（新增 adapter，AgentModelPort 不变）。
- 需要多工具 / 多 Agent / workflow / checkpoint 持久化时（评估是否引入框架；先新建 ADR）。
- provider SDK 升级改变 tool-calling 交互格式时（更新 `adapters/agent_model/deepseek.py`）。