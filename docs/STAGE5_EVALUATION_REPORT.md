# Stage 5 — Evaluation Report（真实评估运行）

> ⚠️ **Stage 5.1 更新**：下文 §2/§3.2 的 routing 指标（46.7% / 60.0%）为 **last-write-wins 混合口径**，
> 已在 Stage 5.1 中被三层模型取代（`routing_steps[]` + primary decision + Router Component 直连）。
> 修复与 before/after 数据见 `docs/STAGE5_1_EVALUATION_STABILIZATION.md`；本文保留为历史基线。

> 运行方式：`scripts/run_evaluation.py`（完整 37 例，`DEEPSEEK_API_KEY` 注入环境变量）。
> 完整逐 case 明细：`.local/eval/eval-20260915-182020.json`；逐事件 trace：`.local/traces/<trace_id>.jsonl`。
> 每次运行均可复现；本报告是快照式结论。

## 1. 运行元信息

| 项 | 值 |
|---|---|
| 数据集 | `examples/evaluation/dev_knowledge_eval.jsonl` |
| 样本数 | 37（9 类：direct_answer 6 / generic 2 / factual 8 / terminology 5 / relationship 4 / multi_document 4 / overview 3 / unknown 3 / insufficient_evidence 2） |
| 运行时间 | 2026-09-15 18:20（UTC+8） |
| 工作区 | `.local/eval_live`（唯一 workspace，隔离文档去重） |

## 2. 总览指标

| 维度 | 指标 | 结果 |
|---|---|---|
| 工具选择 | accuracy / precision / recall | **94.6% / 100.0% / 93.3%**（FP=0，FN=2） |
| 路由意图 | intent_accuracy | **46.7%**（14/30 与期望基线不一致） |
| 路由策略 | strategy_accuracy / fallback_rate | **60.0%** / 0.0% |
| 源覆盖率 | expected_source_recall | **92.0%** |
| 引用 | citation_grounded_rate / citation_source_recall | **100.0% / 92.0%** |
| 答案关键事实 | answer_term_match_rate | **95.5%**（1 例缺术语） |
| 诚实弃答 | abstention_accuracy | **100.0%**（5/5 未知/证据不足均诚实弃答） |
| 性能 | latency p50 / p95 | **3937.6 ms / 6946.0 ms** |
| 成本 | tokens in / out / total | **161229 / 13382 / 174611**（约 4.7k tokens/例） |
| 失败 | failure_counts / failed_case_ids | 空（无系统失败） |

> 说明：`expected_intent/expected_strategy` 是 Stage 3 路由策略的**期望基线**（非客观最优）。
> `intent_accuracy` 度量的是"实际路由与既定策略的一致性"，不是"检索效果最优性"。

## 3. 分维度分析

### 3.1 工具选择（94.6%，2 个假阴性）

误例（`should_call_tool=true` 但模型直接回答，0 次工具调用）：

| case | 问题 | 原因 |
|---|---|---|
| f3 | 401 和 403 有什么区别？ | OAuth/HTTP 语义是通用知识，模型直接作答 |
| t5 | 401 invalid_grant 是什么意思？ | 同上，模型凭通用知识作答 |

结论：没有假阳性（不检索的知识问题从未误触发工具）。两个 FN 均为"通用 HTTP/OAuth 知识"边界案例；
这类基础协议知识是否应强制走 KB 是一个产品决策（可在 system prompt 里收紧 tool 使用指引，也可接受
"常识直答"为合理行为）。

### 3.2 路由意图 / 策略（46.7% / 60.0% —— 显著低于基线）

14 例不一致的**根因（两层，已通过 trace 逐例核实）**：

**A. 末次记录覆盖（5 例，测量聚合伪偏差）** —— o2 / m1 / m2 / m4 / r2
这些例子模型的第一次检索 query 保留了正确信号，`QueryRouter` 也给出了**正确的策略决策**
（o2→overview/global，m1/m2→multi_document/hybrid，m4→relational/hybrid，r2→relational/hybrid），
但模型随后又发了一次"英文回顾式"低信号查询（如 `service architecture components dependencies`）
得到 general/hybrid；`build_case_result` 目前取**最后一个** routing 记录，把正确决策覆盖掉了。
按"首个（主）检索决策"口径，这 5 例全部一致 → **策略一致性上升至 83.3%**。

**B. LLM 改写查询丢失关键标记（9 例）** —— o3 / f5 / f6 / f7 / f8 / t4 / u3 / i1 / i2
模型调用工具时把用户问题压缩，丢掉了规则依赖的标记词：

| case | 用户问题（含标记） | 实际工具 query | 丢失标记 → 落回 general |
|---|---|---|---|
| f5 | 订单详情缓存的 TTL 是**多少**？ | 订单详情缓存 TTL | 是多少 |
| f6 | 允许的下游转发次数是**多少**？ | (下游转发次数…) | 是多少 |
| f7 | critical path 超时阈值是**多少**？ | API Gateway critical path 超时阈值 | 是多少 |
| f8 | green 环境的版本号是**多少**？ | Order Service green 环境 版本号 | 是多少 |
| t4 | 什么是 access token 的 scope？ | access token scope 定义 权限范围 | 是什么 |
| u3 | 提现手续费是**多少**？ | 支付网关 提现手续费 | 是多少 |
| i1 | …恢复步骤以及 RPO/RTO 是**什么**？ | 生产数据库 灾难恢复步骤 RPO RTO | 是什么（→被"步骤"判为 multi_document） |
| i2 | 全年可用性 SLO 和告警阈值是**多少**？ | … | 是多少 |
| o3 | Mercury Commerce Platform 的**总体架构**是怎样的？ | Mercury Commerce Platform architecture | 总体/架构 |

`QueryRouter` 本身是确定且正确的（同一 query 直接喂给 Router 单测全绿）；偏差来自上游
Agent 的 query 改写与下游的 last-record 聚合。**这不是检索器问题，是评估口径与 prompt 行为问题。**

结论与改进项：
1. **评估聚合**：`build_case_result` 应对多次工具记录做聚合（如"主检索=首个决策"或"任一记录命中即一致"），
   而不是末次覆盖 —— 消除 5 例伪偏差。
2. **Prompt 行为**：system prompt 已强调"用原问题检索"，但模型仍会压缩；可在
   `agent/prompts.py` 中显式要求"tool 的 query 参数必须逐字复述用户问题"，并重新评估验证效果。
3. 若以上两条落地，预期策略一致性可回到 80%+（多轮非丢掉信号时接近 100%）。

### 3.3 源覆盖率 / 引用（92.0% / grounded 100%）

- `citation_grounded_rate=100.0%`：所有引用都真实出自工具返回的来源 —— **无幻觉引用**。
- 92.0% 的 source recall 损失集中在 f3 / t5（工具未被调用，`actual_sources=[]`），与 3.1 同一根因；
  排除这 2 例后 source recall 为 **100.0%**。
- 检索到的来源与期望来源逐例对得上（api_auth.md、incident_runbook.md、deployment.md、
  service_overview.md 全部正确命中），SourceResolver 的 basename 解析稳定。

### 3.4 答案关键事实（95.5%）

37 例中 36 例包含期望关键术语（30 分钟 / 7 天 / 401 / Authorization / 300 秒 / v2.4.1 / 连接池 / …）。
唯一缺失：t5（"重新登录"），根因同样是 3.1 的"未调工具直接用通用知识作答"——模型讲了
`invalid_grant` 的正确含义但没有使用与文档一致的关键词。语义上答案正确，度量上算作术语未命中。

### 3.5 诚实弃答（abstention 100.0%）

5 例未知/证据不足（u1 Billing Service / u2 库存幂等 / u3 支付网关手续费 / i1 DR+RPO/RTO / i2 SLO 告警阈值）
**全部诚实弃答**，明确说出"知识库中没有 X"，没有编造任何数值或架构（示例：u1 拒绝编造 Billing 的数据库、
i1 明说"没有完整的 DR 流程与 RPO/RTO 定义"）。
- 值得注意：全程 `no_evidence_rate=0.0%`（RagSearchTool 未返回过 NO_EVIDENCE 状态——Kernel 对未知实体
  仍返回了相关度低的证据），**诚实性由 prompt 的 grounding/abstain 策略 + 弱证据引导实现，而非依赖
  NO_EVIDENCE 状态位**。这验证了"NO_EVIDENCE 与系统错误分离、弃答由 Agent 完成"的设计。

### 3.6 性能与成本

- latency p50/p95 = 3.94s / 6.94s：单例 = 1 次模型调用（工具选择）+ 1 次检索 + 1 次答案合成，
  大部分时延在 LightRAG local/hybrid 检索（4 chunk × embedding 检索 + graph walk）。
- 每例平均约 4.7k tokens（37 例合计 174.6k）；deepseek-chat 回答合成 token 占比较小（13.4k out）。

## 4. 关键结论

| # | 结论 | 证据 |
|---|---|---|
| 1 | **工具选择可靠**：不误触发（FP=0）；2 个 FN 均为"通用 HTTP 知识直答"边界行为 | 94.6% acc，f3/t5 |
| 2 | **引用完全 grounded，无幻觉引用**；来源 basename 解析稳定 | grounded 100%，source recall 92%（排除 f3/t5 后 100%）|
| 3 | **诚实弃答是强项**：未知/证据不足 100% 弃答且不编造 | u1/u2/u3/i1/i2 |
| 4 | **路由一致性被两件事压低（并已定位）**：last-record 聚合伪偏差（5 例）+ 模型改写丢失标记（9 例）；Router 规则本身正确 | trace 逐例核实，见 §3.2 |
| 5 | **失败面干净**：37 例 0 系统失败，所有维度均有确定性指标与逐 case 明细可复核 | failure_counts={} |

## 5. 复现

```powershell
# 1) 注入密钥（不落盘）
$env:DEEPSEEK_API_KEY = (Get-Content .env | Where-Object {$_ -match '^DEEPSEEK_API_KEY='} | ForEach-Object {$_.Split('=',2)[1]})
# 2) 完整评估（或 --limit N）
.\.venv\Scripts\python.exe scripts/run_evaluation.py
# 结果 -> .local/eval/eval-<时间戳>.json；trace -> .local/traces/<trace_id>.jsonl
```

实测的静态断言：`tests/unit/test_evaluation_metrics.py`（指标计算）、`tests/unit/test_trace_order.py`
（trace 顺序）、`tests/integration/test_evaluation_e2e.py`（真实 4 例管线 + 指标 sanity）均覆盖本报告使用的口径。