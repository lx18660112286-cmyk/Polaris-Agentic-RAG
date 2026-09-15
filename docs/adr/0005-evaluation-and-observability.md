# ADR 0005 — Evaluation + Observability（应用自有 Trace 契约 + 确定性评估）

- **Status**: Accepted
- **Date**: 2026-09-15
- **Relates to**: ADR 0001（LightRAG as Kernel）、ADR 0002（Evidence Contract / Search Port）、ADR 0003（Retrieval Routing）、ADR 0004（Single Agent Tool Calling）

## Context

Stage 4 交付了 Single Agent 编排，但系统缺少两件事：

1. **可度量**：无法回答"Agent 工具选择准不准 / 路由是否符合策略 / 引用是否 grounded / 未知问题是否诚实弃答"。
2. **可观测**：一次请求内部的 Agent → Tool → Router → Adapter 调用链、延迟、token、失败原因没有结构化记录，
   出了问题只能靠打印日志猜。

约束与原则：
- 不引入外部监控链路（OpenTelemetry / Langfuse / LangSmith 均列为 Stage 5 Non-goals）——当前只需要"应用自有、可落盘、可复现"的观测。
- 架构边界不变：`evaluation/` 与 `observability/` 不得 import LightRAG / provider SDK；Agent 核心不得依赖 sink 实现。
- 评估指标必须**确定性、可解释**，拒绝"LLM 打分给个模糊质量分"这类黑盒（无法复现、无法驱动修复）。
- 评估必须覆盖 Agent 的核心能力（工具选择）、Stage 3 的路由策略（意图/策略一致性的**期望基线**，非客观最优）、
  引用 groundedness、答案关键事实、以及"未知问题不幻觉"。

## Decision

### 1. Observability：`observability/` 包（应用自有的 Trace 契约）

```text
observability/
 ├─ models.py    Trace / TraceEvent / TraceEventType / FailureCategory
 ├─ tracer.py    Tracer（ContextVar 传播 trace_id，emit 自动脱敏）
 ├─ sinks.py     TraceSink (Protocol) / InMemoryTraceSink / JsonlTraceSink
 └─ analysis.py  agent_latency_ms / sum_attributes（评估用只读分析）
```

核心判断：

1. **`TraceEventType` 是应用词汇**（AGENT_STARTED / MODEL_CALL_STARTED / TOOL_SELECTED /
   ROUTER_DECISION / RETRIEVAL_STARTED / ... / ERROR），与任何后端无关；未来接 OTel/Langfuse 时
   只是新增一个 sink adapter（spec §39），`TraceSink` Protocol 面向"消费事件"而不是"对接厂商"。
2. **低侵入传播**：`Tracer` 用 `ContextVar` 记录当前 `trace_id`，Agent → Tool → Router → Adapter
   无需把 `tracer/trace_id/sink` 当参数层层传递；`Tracer.emit` 在无活动 trace 时是 no-op，
   fake/单测零成本。
3. **脱敏是硬边界**：`redact_attributes` 在事件到达任何 sink 之前替换 secret 类键名
   （`api_key / authorization / password / access_token / ...`）与 chain-of-thought 键
   （`reasoning / thinking / ...`）——这种事决不能在 sink 层才做（spec §33/§34）。
4. **正确区分失败类别**：`FailureCategory` 把 `NO_EVIDENCE`（诚实弃答，正常业务结果）与
   `MODEL_ERROR / TOOL_ERROR / MAX_STEPS ...`（系统失败）分开，评估汇总绝不把业务结果当错误。

### 2. Evaluation：`evaluation/` 包（确定性评分，不引入 LLM 裁判）

```text
evaluation/
 ├─ models.py    EvalCase / EvalCaseResult / EvalRunResult / MetricSummary
 ├─ metrics.py   confusion matrix / source recall / citation groundedness / abstention ...
 ├─ evaluator.py build_case_result(AgentResult + trace -> 每维判定)
 └─ runner.py    EvaluationRunner（load -> run -> evaluate -> print -> save）
```

关键维度与指标（全部确定性）：

| 维度 | 指标 | 含义 |
|---|---|---|
| 工具选择 | `tool_selection_accuracy` + precision/recall（TP/TN/FP/FN） | 该不该调工具 vs 实际是否调 |
| 路由意图 | `intent_accuracy` | 实测 intent == 数据集期望基线 |
| 路由策略 | `strategy_accuracy` / `fallback_rate` | 实测 strategy == 期望基线；显式回退占比 |
| 源覆盖率 | `expected_source_recall` | 期望来源（如 api_auth.md）是否在工具实际来源中 |
| 引用 grounded | `citation_grounded_rate` / `citation_source_recall` | 引用必须出自工具实际来源；期望来源进引用占比 |
| 答案关键事实 | `answer_term_match_rate` | 答案是否包含期望关键术语（如 "30 分钟"） |
| 诚实弃答 | `abstention_accuracy` | 未知/证据不足问题是否弃答而非编造 |
| 性能 | `latency_p50/p95` / 输入/输出/总 token | 来自 trace 的 MODEL_CALL_COMPLETED 与 AGENT 首尾事件 |

- `EvaluationRunner` 框架无关：只接收 `run_case: Callable[[EvalCase], Awaitable[EvalCaseResult]]`，
  由 CLI / 集成测试把真实组合 Agent 接进来；`evaluation/` 从不 import LightRAG / provider。
- 运行结果整体落盘 `.local/eval/eval-<时间戳>.json`（gitignored），每个 case 的 expected + actual +
  每维判定齐备，报告可复现。

### 3. 数据与入口

- 评估数据集 `examples/evaluation/dev_knowledge_eval.jsonl`：37 例、9 类
  （direct_answer / generic / factual / terminology / relationship / multi_document / overview /
  unknown / insufficient_evidence）。
- CLI `scripts/run_evaluation.py --limit N`；`scripts/run_agent.py --debug` 打印每次查询的 trace。
- 埋点位置（不改变业务语义）：orchestrator（AGENT/MODEL/TOOL/ERROR）、RagSearchTool（ROUTER/RETRIEVAL）。

## Alternatives Considered

### 评估替代：LLM-as-judge 综合质量分

**拒绝。** 黑盒、不可复现、无法定位到具体维度、cost 高；当前维度都能用确定性规则判（Confusion matrix /
集合 recall / 术语包含）。判定与判定理由全部可溯源到原始事件与结果字段。

### 观测替代一：直接内嵌 OpenTelemetry

**暂不引入。** 当前单进程、单知识库、无分布式需求，OTel 的 span/attribute/resource 语义对本项目是
过度设计；先拥有自有的小契约，未来扩展为 OTel sink 即可（`TraceSink` 已准备好）。

### 观测替代二：埋点写业务日志 / print

**拒绝。** 不可结构化、不可按 trace_id 关联、无法做评估输入。所有观测走 `TraceSink`，
`observability/` 自身绝不 print。

## Consequences

正面影响：
- Agent 行为首次可度量：工具选择 / 路由一致性 / 引用 grounded / 诚实弃答 / 延迟与 token 一目了然；
- trace 关联整条调用链（一个 `trace_id` 贯穿 Agent → Tool → Router → Adapter）；
- 失败分类把"系统错误"与"正常业务结果（NO_EVIDENCE）"分开，评估与告警不会被误报淹没；
- 切换/接入外部观测后端只新增一个 sink，不触碰业务埋点。

代价：
- 新增 `observability/` + `evaluation/` 两个包与相应架构 guard，学习/维护面变大；
- 评估运行需要真实 provider 凭证（离线单元测的是指标计算与 trace 顺序，真实 run 是集成测试）；
- 数据集是"路由策略期望基线"而非客观最优答案——指标高只代表"与策略一致"，不等于"检索最优"
  （推导结论时必须说明这一点）。

## When To Revisit

- 引入 OpenTelemetry / Langfuse / LangSmith 时（新增 sink adapter，本契约不变）。
- 需要"检索效果最优"这类客观评估时（引入 answer-level 评估与多 baseline 对比，需新建 ADR）。
- Stage 6 External Tools 落地后（trace/evaluation 需覆盖 Git/Log/Database/Web 工具维度）。