# Stage 4 — Single Agent Orchestrator

> 目标：在 Stage 3 的检索链之上，新增一个真正的 Single Agent，它能接收用户消息、判断是否
> 需要检索、调用 `RagSearchTool`（原生 Tool Calling），并基于结构化 evidence 产出最终答案。

## 1. Agent 架构

```text
User
 ↓
AgentOrchestrator
 ↓
ToolRegistry
 ↓
AgentRagSearchTool   (薄 wrapper of RagSearchTool)
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

两层 Routing 严格分离：
- **Layer 1（Agent）**：`tool_choice="auto"`，由 LLM 决定"要不要调 `search_dev_knowledge`"。
- **Layer 2（RAG）**：`RagSearchTool -> QueryRouter` 决定"怎么检索（strategy/top_k）"。
- Agent 永不接触 `mode / top_k / rerank`。

## 2. AgentModelPort

```python
@runtime_checkable
class AgentModelPort(Protocol):
    async def complete(messages: list[AgentMessage], tools: list[ToolDefinition]) -> AgentModelResponse: ...
```

- provider-neutral；Agent 核心不 import openai。
- `DeepSeekAgentModelAdapter`（`adapters/agent_model/deepseek.py`）是唯一 import `openai` 的地方，
  负责 domain ↔ provider wire 转换，并把错误归一化为 `DeepSeekAgentModelError`。
- `openai` 已声明为根项目 runtime dependency（非经 LightRAG 的传递依赖）。

## 3. Agent 领域模型（`agent/models.py`）

`AgentRole / AgentMessage / AgentToolCall / AgentModelResponse / AgentStatus / AgentResult /
ToolCallRecord`。能表达 assistant text、tool_calls、tool_call_id、tool name、arguments。
`openai.types.chat.*` 不透出。

`AgentResult`：`status ∈ {SUCCESS, TOOL_ERROR, MAX_STEPS_EXCEEDED, MODEL_ERROR}` + `answer /
citations / tool_calls / steps / error`。

## 4. Tool Registry（`tools/registry.py`）

- 注册：`search_dev_knowledge`（通过 `AgentRagSearchTool` 薄 wrapper）。
- 重复注册 → `DuplicateToolError`；未知工具 → `UnknownToolError`。
- `invoke(name, raw_arguments)`：JSON parse → input schema 校验 → invoke；失败 → `InvalidToolArgumentsError`。
- `definitions()` 返回 provider-neutral 的 `ToolDefinition`；tool schema 由 `RagSearchInput.model_json_schema()` 生成，不长两份。

## 5. Agent Loop

```text
system -> user -> model
   ├─ no tool_calls -> final answer
   └─ tool_calls
        ├─ max_tool_calls / max_steps / duplicate guard
        ├─ ToolRegistry.invoke (validate) -> tool result
        └─ append tool result -> model -> final answer / more calls
```

原生 tool calling；不用自定义 ACTION 文本协议；几十行状态机（不引入 LangGraph 等）。

## 6. Tool Selection（真实观察）

| 问题 | 决策 | 说明 |
|---|---|---|
| 你好，请简单介绍一下你能做什么 | 直接回答 | 0 次 tool call |
| Access token 的有效期是多少？ | 调 `search_dev_knowledge` | ≥1 次 tool call，依据 evidence 回答 |
| 整个系统的核心组件和关系是什么？ | 调工具 + MULTI_DOCUMENT/OVERVIEW 路由 | 由 QueryRouter 决定 strategy |

## 7. Grounding / Citation / Failure（写在 system prompt）

- 内部知识事实必须基于 tool evidence；不得补自创项目事实。
- 引用 source：`[api_auth.md]`；多文件 `[deployment.md] [incident_runbook.md]`；不伪造 reference。
- `NO_EVIDENCE` → 明确"知识库没有足够信息"；`ERROR` → 说明检索暂时失败；均不得编造。
- 不暴露 `mode / top_k / rerank` 等 kernel detail。

## 8. Failure / Termination

- malformed JSON / 缺字段 / 未知字段 → `InvalidToolArgumentsError` → 作为 tool message 反馈，不外泄 traceback。
- unknown tool → `UnknownToolError`。
- duplicate identical call → 拒绝执行并记录 `duplicate`。
- 超 `max_steps` → `MAX_STEPS_EXCEEDED`；超 `max_tool_calls` → `TOOL_ERROR`。
- 模型调用异常 → `MODEL_ERROR`（归一化，不泄漏 SDK 异常）。

## 9. 组合根（`bootstrap.build_agent`，返回 `BuiltAgent`）

```text
Settings
 ↓
LightRAGAdapter    →  RagSearchTool → AgentRagSearchTool → ToolRegistry
 ↓                                       ↓
                                       build_system_prompt
 ↓
DeepSeekAgentModelAdapter  →  AgentOrchestrator
```

`BuiltAgent{ rag_tool, registry, orchestrator, adapter }`：调用方（CLI / 集成测试）负责
`adapter.initialize() / close()` 生命周期。

## 10. Offline Unit Tests（FakeModel / FakeTool）

- `test_tool_registry.py`：register / duplicate / get / unknown / definitions / valid / invalid args / schema-extra。
- `test_agent_orchestrator.py`：direct answer、tool→final、NO_EVIDENCE、tool ERROR、unknown tool、
  invalid JSON、schema failure、duplicate、max steps、max tool calls、model error、system prompt 首条。
- `test_agent_model_contract.py`：Port 签名无 openai 类型、fake 结构兼容。
- `test_agent_prompts.py`：policy markers + 不暴露 kernel 值。

## 11. Real Agent E2E（`test_agent_e2e.py`）

真实路径（build → init → ingest → run → close，try/finally）：
- A) 直接回答：问候 → 0 tool call。
- B) 工具路径：`Access token 的有效期是多少？` → 调工具，answer 含 "30"，citations 含 `api_auth.md`。
- C) 未知：`Billing Service 使用什么数据库？` → 调工具 → NO_EVIDENCE → 明确无足够信息。

断言为**语义关键点**（substring / citations / tool count / status），不断言整句。

## 12. Limitations

- LLM tool 选择不 100% 稳定：真实 E2E 用宽松断言 + 语义要点。
- 只支持单模型（DeepSeek/OpenAI 兼容）；换 provider 需新 adapter。
- 无长期记忆 / checkpoint / 会话持久化（Stage 4 Non-goal）。
- 无完整 observability backend（Stage 5）。

## 13. Stage 5 Implications

Evaluation + Observability：为 retrieval / routing / tool-selection / answer groundedness /
citation correctness / latency / token usage / failure taxonomy / agent+tool+router traces
建立可度量框架；`ToolCallRecord` 与 `AgentResult` 是现成的 trace 载体。

## 14. Stage 6 Implications

外部工具（Git/Log/DB/Web）进入时，只需实现 `AgentTool` 并注册进 `ToolRegistry`；
Agent 的 tool 选择将由 `tool_choice="auto"` 处理多工具场景，无架构改动。

---
更新时机：本报告随 pinned commit 与真实运行结果更新；若 provider SDK 或 kernel 升级改变
tool-calling / `aquery_data` 行为，需重跑 baseline / 集成测试并更新本文件。