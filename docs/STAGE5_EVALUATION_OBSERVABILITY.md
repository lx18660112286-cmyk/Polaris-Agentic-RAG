# Stage 5 — Evaluation + Observability

> 目标：在 Stage 4 的 Single Agent 之上，建立**可度量、可观测**闭环——用确定性指标评估 Agent 的
> 工具选择 / 路由一致性 / 引用 groundedness / 诚实弃答 / 性能，用结构化 trace 记录整条调用链。

## 1. 总览

```text
                           ┌────────────────────┐
User ──▶ AgentOrchestrator │  Tracer (ContextVar)│──▶ TraceSink ──▶ InMemory / Jsonl
             │ MODEL/TOOL│                      │                       │
             ▼ 埋点       └────────────────────┘                       ▼
        ToolRegistry                                              .local/traces/<trace_id>.jsonl
             ▼
        RagSearchTool (ROUTER/RETRIEVAL 埋点)
             ▼
        QueryRouter ──▶ RetrievalPlan ──▶ KnowledgeSearchPort ──▶ LightRAGAdapter ──▶ LightRAG

Evaluation:  dataset(EvalCase) ──▶ build_agent ──▶ run_case ──▶ build_case_result ──▶ metrics ──▶ .local/eval/*.json
```

- **观测**：一次请求一个 `trace_id`，贯穿 Agent → Tool → Router → Adapter，事件全部落到 sink。
- **评估**：37 例标注数据集逐条跑真实 Agent，`EvalCaseResult` 记录 expected + actual + 每维判定，
  汇总为确定性 `MetricSummary`。

## 2. Observability 契约（`observability/`）

### 2.1 事件类型 `TraceEventType`（应用词汇，与后端无关）

`AGENT_STARTED / MODEL_CALL_STARTED / MODEL_CALL_COMPLETED / TOOL_SELECTED /
TOOL_CALL_STARTED / TOOL_CALL_COMPLETED / ROUTER_DECISION / RETRIEVAL_STARTED /
RETRIEVAL_COMPLETED / AGENT_COMPLETED / ERROR`

> 未来接 OTel / Langfuse 只是新增一个 `TraceSink` adapter（spec §39），契约本身不动。

### 2.2 失败分类 `FailureCategory`

`NO_EVIDENCE`（诚实弃答，**正常业务结果**）与系统失败分离：

- 系统失败：`MODEL_ERROR / TOOL_ERROR / INVALID_TOOL_ARGUMENTS / UNKNOWN_TOOL /
  MAX_STEPS / MAX_TOOL_CALLS / ROUTING_FALLBACK / RETRIEVAL_ERROR / CITATION_ERROR`
- 评估汇总里 `failure_counts` 只统计系统失败；`no_evidence_rate` 单列。

### 2.3 低侵入传播与脱敏

- `Tracer` 用 `ContextVar` 传播 `trace_id`，埋点处无需传参；无活动 trace 时 `emit` 为 no-op。
- `redact_attributes` 在事件到达 sink **之前**替换 secret / chain-of-thought 键值
  （`api_key / authorization / access_token / reasoning / thinking / ...`）。

## 3. Evaluation（`evaluation/`）

### 3.1 评估维度与确定性指标

| 维度 | 指标 | 判定来源 |
|---|---|---|
| 工具选择 | accuracy / precision / recall（混淆矩阵） | `should_call_tool` vs 实际 `tool_calls` |
| 路由意图 | `intent_accuracy` | trace/结果里的实际 intent vs 数据集期望 |
| 路由策略 | `strategy_accuracy` / `fallback_rate` | 实际 strategy vs 期望；显式回退占比 |
| 源覆盖率 | `expected_source_recall` | 期望来源（api_auth.md…）∩ 工具实际来源 |
| 引用 grounded | `citation_grounded_rate` / `citation_source_recall` | 每个引用必须出自工具实际来源 |
| 答案关键事实 | `answer_term_match_rate` | 答案包含期望关键术语（如 "30 分钟"） |
| 诚实弃答 | `abstention_accuracy` | 未知/证据不足是否弃答而非编造 |
| 性能 | latency p50/p95、in/out/total tokens | trace 的 AGENT 首尾与 MODEL_CALL_COMPLETED |

所有指标纯确定性（集合 / 混淆矩阵 / 字符串包含），**无 LLM 裁判**，可在 `.local/eval/eval-*.json`
里逐 case 复现。

### 3.2 `EvaluationRunner` 生命周期

`load_dataset ——▶ (循环) run_case ——▶ build_case_result ——▶ compute_metrics ——▶ save/print`

- `run_case` 由调用方注入：CLI / 集成测试把**真实组合 Agent** 接进来，框架本身不 import LightRAG。
- CLI：`scripts/run_evaluation.py [--limit N] [--dataset PATH]`；`scripts/run_agent.py --debug`
  打印每次查询的 trace 事件。

## 4. 埋点清单

| 位置 | 事件 |
|---|---|
| `AgentOrchestrator.run` | AGENT_STARTED / MODEL_CALL_STARTED·COMPLETED / TOOL_SELECTED / TOOL_CALL_STARTED·COMPLETED / AGENT_COMPLETED / ERROR |
| `RagSearchTool.invoke` | ROUTER_DECISION / RETRIEVAL_STARTED·COMPLETED |

模型输出 token 真实计数通过 `DeepSeekAgentModelAdapter` 返回的 `usage` 透传到
MODEL_CALL_COMPLETED（`input_tokens / output_tokens / total_tokens`）。

## 5. 质量门禁与交付物

- 新增 `tests/unit/test_evaluation_metrics.py`（混淆矩阵 / source recall / citation / abstention）、
  `tests/unit/test_observability_tracer.py`（emit / span / 脱敏）、
  `tests/unit/test_trace_order.py`（trace 顺序与失败处理）、`test_observability_sinks.py` 等。
- 架构 guard 扩展：`evaluation/`、`observability/` 不得 import lightrag / adapters / provider SDK。
- 集成（真实 E2E）：`tests/integration/test_evaluation_e2e.py`——4 例（direct/factual/terminology/
  unknown）真实跑完整评估管线并断言指标 sanity。

## 6. 真实评估结果

见 `docs/STAGE5_EVALUATION_REPORT.md`（每次运行的完整 case 明细在 `.local/eval/eval-<时间戳>.json`）。

> 注意：`expected_intent / expected_strategy` 是"路由策略期望基线"（Stage 3 规则的既定策略），
> 指标高只代表"与策略一致"，不等于"检索效果客观最优"。