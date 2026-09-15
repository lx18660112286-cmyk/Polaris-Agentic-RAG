# Stage 5.1 — Evaluation Stabilization（评估稳定化）

> 状态：✅ 已交付（2026-09-16）。
> 运行方式：`scripts/run_evaluation.py`（完整 37 例，`DEEPSEEK_API_KEY` 注入环境变量，
> `router=built.rag_tool.router` 接入 Layer B 组件评估）。
> 完整逐 case 明细：`.local/eval/eval-20260915-194730.json`（after）与
> `.local/eval/eval-20260915-182020.json`（before）；逐事件 trace：`.local/traces/<trace_id>.jsonl`。

本阶段**不增加新能力**，目标是修正 Stage 5 真实评估暴露的四类问题并完成三层归因
（spec §1-§2）：

1. routing aggregation measurement artifact（末次记录覆盖首次决策）
2. Agent query rewrite 导致的 retrieval intent drift
3. Retrieval Invocation false-negative 核查
4. 多层 Evaluation 归因不清晰（Router 自身 vs Agent→Tool 链路）

## 1. 变更内容

### 1.1 Query Provenance + RoutingStep（spec §6/§9/§20）

- `retrieval/models.py` 新增 `RoutingStep`：`step_index / tool_call_id / original_user_query /
  tool_query / intent / strategy / reason / fallback_used`。一次 Agent request 的所有路由步骤
  独立保存，事件用 `tool_call_id` 关联（不依赖事件列表位置）。
- `AgentOrchestrator` 采集每次知识检索调用的 `(original_user_query, tool_query, RoutingDecision)`
  三元组；`original_user_query` 不可变，`tool_query` 是实际发送给 `search_dev_knowledge` 的查询。
- `RagSearchTool` 的 **API 保持 `search(query)` 不变**（spec §10），provenance 由 Agent/Trace 保存。
- Trace 新增 `tool_call_scope(tool_call_id)` 上下文，`TOOL_SELECTED / TOOL_CALL_STARTED /
  TOOL_CALL_COMPLETED` 事件携带 `tool_call_id`。

### 1.2 Primary Routing Decision（取消 last-write-wins，spec §6-§8）

- `EvalCaseResult` 的 Layer C 取**首个 routing step** 作为 primary retrieval decision；
  后续步骤（如二次英文回顾式低信号查询）不再覆盖首次决策。
- 同时输出 `all_routing_steps_count` / `routing_fallback_rate`，多步查询全部保留可审计。

### 1.3 三层度量拆分（spec §2/§21/§27）

| 层 | 度量 | 口径 |
|---|---|---|
| Layer A — Retrieval Invocation | accuracy / precision / recall / FP / FN | Agent 是否调用工具（`Retrieval Invocation`，通过原生 `RagSearchTool` 调用行为度量） |
| Layer B — Router Component | intent / strategy / fallback rate | 原始 dataset query 直连 `QueryRouter`，**不经 Agent / Tool / 改写** |
| Layer C — Agentic Retrieval | primary intent / strategy / drift count | Agent 生成的 `tool_query` 经 Router 后的**首次**决策 |

旧的单一 `routing_accuracy`（混合指标）已移除，不再把两层混在一起（spec §2）。

### 1.4 Query Rewrite Diagnostics（spec §12-§14/§18/§19）

- `EvalCase` 增加人工标注 `critical_terms`（spec §13，37 例数据集的 30 个 tool 用例全覆盖）。
- 新增 `critical_term_preservation_rate`（简单、可解释的实体/错误码/约束保留率，非语义相似度）。
- `query_rewrite_drift`：改写后丢关键术语，或原始 query Router 命中期望而改写 query 落空
  （intent flip）→ 归因 `QUERY_REWRITE_INTENT_DRIFT`，不再错误归因为 Router 失败。
- `FailureCategory` 新增 `QUERY_REWRITE_INTENT_DRIFT`、`EVALUATION_AGGREGATION_ERROR`；
  后者修复后真实运行中为 0（spec §19）。
- `agent/prompts.py` 增加改写保留策略（spec §11）：**不强制逐字复述**，要求保留 retrieval
  intent、命名实体、错误码、数值约束、操作动作与问题范围；未做任何 per-query hardcode（spec §16）。

## 2. Before / After 对比（同一 37 例、同一知识库、同一 provider/model、LightRAG 02dcd8d）

| Metric | Stage 5（before） | Stage 5.1（after） | 口径说明 |
|---|---:|---:|---|
| Retrieval Invocation accuracy | 94.6% | **97.3%** | 同口径（FP=0，FN 2→1） |
| Retrieval Invocation precision | 100.0% | **100.0%** | 同口径 |
| Retrieval Invocation recall | 93.3% | **96.7%** | 同口径 |
| Router Component intent | N/A | **90.0%**（27/30） | 新指标（spec §3） |
| Router Component strategy | N/A | **93.3%**（28/30） | 新指标 |
| Router Component fallback | N/A | **0.0%** | 新指标 |
| Primary Agentic intent | 46.7%（旧混合口径） | **89.7%**（26/29） | **口径改变**（primary step） |
| Primary Agentic strategy | 60.0%（旧混合口径） | **93.1%**（27/29） | **口径改变** |
| Query rewrite drift | 14 例偏差（未分因） | **3** | 新指标（spec §18） |
| Critical term preservation | N/A | **96.7%** | 新指标（spec §14） |
| Expected source recall | 92.0% | **96.0%** | 同口径 |
| Citation grounded | 100.0% | **100.0%** | 同口径，无回归 |
| Citation source recall | 92.0% | **96.0%** | 同口径 |
| Answer term match | 95.5% | **100.0%** | 同口径 |
| Abstention accuracy | 100.0% | **100.0%** | 同口径，无回归 |
| System failures | 0 | **0** | 同口径 |
| Latency p50 / p95 | 3937.6 / 6946.0 ms | **3453.0 / 5401.8 ms** | 同口径 |
| Tokens（in/out/total） | 161229 / 13382 / 174611 | 145243 / 12403 / **157646** | 同口径 |
| tokens per case | 约 4.7k | **4260.7** | 同口径 |
| model calls / tool calls per case | 未记录 | **1.78 / 0.84** | 新记录（spec §23） |

> ⚠️ 按 spec §27：旧的 routing metric 与新的 metric **定义不同**（mixed last-write-wins →
> primary step + Router 直连），不能直接声称 “60% → 93%”。表内已注明口径改变。
> 其余指标同口径，可直接比较。

## 3. 分层结果与归因

### 3.1 Layer A — Retrieval Invocation（97.3%）

FP=0，FN=1：

| case | query | 预期 | 实际 | FP/FN |
|---|---|---|---|---|
| f3 | 401 和 403 有什么区别？ | 调工具 | 直接回答 | FN |

- t5（before 的另一个 FN）已修正：本轮真实调用工具并路由到 `terminology/focused`，primary 命中。
- 唯一剩余 f3：模型用通用 HTTP/OAuth 语义直接作答（内容正确，含 401/403 术语，答案术语命中 100%）。
  这是“通用协议知识直答”边界行为，before 报告中已记录为产品决策候选；**未做 per-query hardcode**，
  保留为已知边界（spec §16 只允许修 generalizable policy，现状工具选择 policy 已表达
  “内部运营知识 → 先检索”）。

### 3.2 Layer B — Router Component（intent 90.0% / strategy 93.3%）

Router 直接路由原始 query，3 例偏离期望基线（均为确定性规则边界，非 Agent 问题）：

| case | query | 期望 | 实际 | 原因 |
|---|---|---|---|---|
| t4 | 什么是 access token 的 scope？ | terminology/focused | general/hybrid | 规则未识别 “scope” 术语特征 → 落入默认 hybrid |
| r4 | API Gateway 与 Auth Service 是什么关系？ | relational/hybrid | terminology/focused | “…是什么关系” 命中 terminology “是什么” 规则 |
| m4 | 如何诊断数据库连接耗尽的问题？ | multi_document/hybrid | relational/hybrid | “如何诊断” 触发 relational 依赖倾向规则 |

> 按 spec §17：Router Component（90%/93.3%）已明显高于旧 Agentic 混合口径，且偏差为规则边界个例，
> **不对 Router 做大改**（禁止 keyword soup）；记为后续可选精化项，不影响本阶段 SUCCESS 判定。

### 3.3 Layer C — Agentic Retrieval（primary intent 89.7% / strategy 93.1%）

29 个产生 routing step 的用例中 3 例 primary 偏离；31 个 routing steps（g2、m1 各 2 步，
多步查询现已全部保留，不再发生末次覆盖）。query rewrite drift 计 3：

| case | 原始 query（Router 判定） | 工具 query | primary 实际 | 归因 |
|---|---|---|---|---|
| g2 | 我想了解…平台组件…（general/hybrid ✓） | 平台组件 架构 依赖 | overview/global ✗ | **改写漂移**（intent flip） |
| i1 | …灾难恢复步骤以及 RPO/RTO 是**什么**？（terminology/focused ✓） | 生产数据库完整灾难恢复步骤 RPO RTO | multi_document/hybrid ✗ | **改写漂移**（丢掉 “是什么” → 被 “步骤” 判 multi_document） |
| m4 | 如何诊断数据库连接耗尽的问题？（relational ✗，Router 自身偏离） | 同源改写 | relational/hybrid ✗ | **Router 规则边界**，非改写（无 intent flip） |
| f3 | 401 和 403 有什么区别？ | （未调工具，无 tool_query） | — | **FN 副作用**：无工具调用 → 关键术语视为全丢失 |

> i1 与 m4 是因果分层的典型证据：i1 Router 直连正确、改写后漂移 → 归因 `QUERY_REWRITE_INTENT_DRIFT`；
> m4 Router 直连已偏、改写未翻案 → 归因 Router 规则。两者不再混在同一个 “routing_accuracy” 里。

### 3.4 Multi-step 查询保留（原 aggregation artifact 已消除）

| case | step 0（primary） | step 1（保留，不覆盖） |
|---|---|---|
| m1 | Order Service 发布后大量 5xx 排查步骤 是否回滚 判断标准 → multi_document/hybrid ✓ | Order Service 服务架构 依赖 上下游 → overview/global |
| g2 | 平台组件 架构 依赖 → overview/global | platform components service architecture dependencies → general/hybrid |

before 中被 “英文回顾式低信号查询” 覆盖的 m1 用例，本轮以 step 0（首次决策）为准命中期望。

### 3.5 失败分类

- 真实运行 **0 系统失败**、0 `EVALUATION_AGGREGATION_ERROR`（修复后符合 spec §19 预期）。
- 唯一 `QUERY_REWRITE_INTENT_DRIFT` 标签落在 f3（FN 副作用，见 3.3），非真实改写；g2/i1
  为真实改写漂移但通过 `query_rewrite_drift` 字段 + metrics 暴露，未进 hard-failure 分类。

## 4. Query Provenance 真实示例（spec §9/§37.6）

```json
{
  "case_id": "i1",
  "original_user_query": "生产数据库完整灾难恢复步骤以及 RPO/RTO 是什么？",
  "tool_query": "生产数据库完整灾难恢复步骤 RPO RTO",
  "router_component_decision": {"intent": "terminology", "strategy": "focused", "match": true},
  "primary_agentic_decision": {"intent": "multi_document", "strategy": "hybrid", "match": false},
  "failure_layer": "QUERY_REWRITE_INTENT_DRIFT"
}
```

三层并存于 `.local/eval/eval-20260915-194730.json`（`router_component.cases` + `cases[].routing_steps`
+ `cases[].router_*`），且 trace 中每条 routing step 带 `tool_call_id` 可与
`TOOL_CALL_STARTED/COMPLETED` 事件一一关联。

## 5. Regression 指标（spec §22 保持项）

| 项 | Stage 5.1 |
|---|---|
| Citation groundedness | **100.0%**（无幻觉引用） |
| Abstention accuracy | **100.0%**（5/5 未知/证据不足诚实弃答） |
| no_evidence_rate | 0.0%（弃答由 prompt 弱证据引导，非状态位依赖，与 Stage 5 一致） |
| System failures | 0 |

## 6. 性能与成本（spec §23/§24）

- latency p50/p95 = **3453.0 / 5401.8 ms**（单例 = 模型调用 + 检索 + 答案合成，主要时延在
  LightRAG local/hybrid 检索 + graph walk）。
- tokens：in 145243 / out 12403 / total 157646；**tokens per case = 4260.7**；
  model calls per case = 1.78；tool calls per case = 0.84。
- `total_tokens` 仅统计 Agent 模型调用（DeepSeek）usage；**LightRAG Kernel 内部 LLM usage
  无法可靠获取 → 标记 not available**，不把 Agent tokens 冒充系统 tokens（spec §24）。

## 7. Quality Gates

```text
pytest -m "not integration"   -> 188 passed
pytest -m integration         -> 6 passed（含 test_evaluation_e2e 真实链路 + provenance 断言）
ruff check src tests scripts  -> All checks passed!
mypy src                      -> Success: no issues found in 45 source files
architecture guard            -> 通过（evaluation/observability 不 import LightRAG/provider SDK）
```

新增/更新测试（spec §28/§29）：
- `tests/unit/test_evaluation_models.py`、`test_evaluation_evaluator.py`、`test_evaluation_metrics.py`：
  primary=first decision / 多步保留 / tool_call_id 关联 / router component bypasses Agent /
  agentic uses tool_query / rewrite drift 分类 / original_user_query immutable / 分层 metrics。
- `tests/unit/test_failure_taxonomy.py`：`QUERY_REWRITE_INTENT_DRIFT` / `EVALUATION_AGGREGATION_ERROR`。
- `tests/unit/test_trace_order.py`：tool_call_id scope 事件关联。
- `tests/integration/test_evaluation_e2e.py`：真实 Agent → 改写 tool_query → Router → Retrieval
  链路验证 provenance 三元组并存（spec §29）。

## 8. Acceptance Criteria 对照（spec §36）

| 标准 | 满足 |
|---|---|
| routing events 不再互相覆盖 | ✅ `routing_steps[]` 全量保留，primary=首次 |
| primary routing decision 定义 | ✅ spec §7 首决策语义 |
| Router Component Evaluation 分离 | ✅ Layer B 直连，不经 Agent |
| Agentic Retrieval Evaluation 分离 | ✅ Layer C primary step |
| original_user_query 捕获 | ✅ 不可变，每条 step 携带 |
| tool_query 捕获 | ✅ AgentOrchestrator 记录 |
| routing/tool calls 关联 | ✅ tool_call_id（事件 + RoutingStep） |
| query rewrite drift 可观测 | ✅ 3 例 + preservation 96.7% |
| Retrieval Invocation mismatches 识别 | ✅ FN=1（f3），无 FP |
| 无 dataset 用例删除 | ✅ 37 例不变（仅加 critical_terms metadata） |
| 无 per-query hardcode | ✅ 只改 prompt 通用改写策略 |
| Citation groundedness 无回归 | ✅ 100% |
| Abstention 无回归 | ✅ 100% |
| offline / integration 全绿 | ✅ 见 §7 |
| 同 37 例重跑 | ✅ 同 KB / 同模型 / LightRAG 02dcd8d |
| before/after 报告 | ✅ 本文 §2-§6 |
| LightRAG submodule 不变 | ✅ 02dcd8d |
| git commit | ✅ `fix: stabilize agent evaluation and routing attribution` |

## 9. Git

- 项目 commit：Stage 5.1 提交（见 `git log -1`）。
- LightRAG submodule：`02dcd8df754ec312b807bdd4d67737b97bc38679`（不变）。
- 工作区：提交后 clean。

## 10. Next Stage（本阶段完成后停止）

项目至此 **FEATURE COMPLETE / FEATURE FREEZE**。原「Stage 6 — Multi-Tool Developer Agent
（GitTool / LogTool / DatabaseTool / WebTool）」**已从正式路线移除，不进入实施计划**；它不属于
当前 Agentic RAG scope（见 `docs/ROADMAP.md` 的 Optional Future Work）。本项目以单一知识能力
`RagSearchTool` 为目标，不以多 Tool orchestration 为目标。