# ADR 0006 — Data Flywheel（人工审核、可审计、回归门禁的旁路学习路径）

- **Status**: Accepted
- **Date**: 2026-09-16
- **Relates to**: ADR 0005（Evaluation + Observability）、ADR 0004（Single Agent Tool Calling）

## Context

Stage 5 / 5.1 交付了确定性评估（三层归因）与结构化观测（trace / 失败分类），系统能回答
"Agent 现在干得如何"。但缺少**闭环**：真实运行时暴露的失败、用户反馈、知识缺口，如何转成
可追溯的改进动作与回归用例，而不破坏运行时稳定性？

关键约束（spec §1/§2）：

1. **旁路能力**：Runtime Path（正常问答）与 Learning Path（飞轮）彻底解耦；飞轮故障不影响问答。
2. **绝对禁止自动修改系统**：不自动改 Prompt / Router / Knowledge Base，不做自动在线学习。
   只能走 `feedback → capture → classify → review → proposal → regression test →
   human approval → apply separately`。
3. **Human-reviewed、Auditable、Reproducible、Regression-gated**。
4. **复用**既有 Trace / AgentResult / EvalCase 契约（spec §44/§45），不建第二套模型。

## Decision

新增 `flywheel/` 包，作为学习路径协调根 `DataFlywheelService`，只做**数据状态迁移**，
永不修改运行时系统。

### 1. 数据流与组件

```text
FeedbackEvent -> ReviewCandidate -> Human Review -> ImprovementProposal
   (原文绑定 trace_id)         (规则 A-E §47)    (mandatory gate §19)
        -> EvalCandidate -> Regression Result -> Human Decision
```

组件：`models.py`（领域模型）/ `repository.py`（JSONL） / `sanitizer.py`（secret redaction）/
`review_queue.py` / `candidate_generator.py`（确定性规则）/ `proposals.py` / `eval_promotion.py` /
`regression.py` / `metrics.py` / `service.py`。

### 2. 关键设计判断

1. **多个模型层级、确定性分类**：`FeedbackType` 不是二元赞/踩而是"为什么"；`FailureLayer`
   接续 Stage 5.1 归因（rewrite drift → `QUERY_REWRITE` 而非 `ROUTER`）；`ImprovementCategory`
   把 `KNOWLEDGE_GAP` 作为一等类别；`ReviewPriority` 用粗粒度枚举而非伪造打分公式。
2. **ReviewCandidate 是反思信号而非判决**：进队列 ≠ 系统有 bug。人工 review 填 category/
   failure_layer/notes（spec §19 是强制门禁）。
3. **proposal 只生成不应用**（spec §28/§75）：`UPDATE_KNOWLEDGE_BASE` 等提案只记录，
   落地需人工从可信来源单独执行。
4. **EvalCandidate 显式提升**（spec §24）：只标记 `PROMOTED`，绝不自动追加数据集文件。
5. **回归门禁**（spec §31-§34）：`RegressionGate` 逐项 delta + hard gate（`hard_tolerance=0.01`）
   + `tests_passed`；决策记给人工，不自动 ACCEPT。
6. **数据最小化 + 脱敏**（spec §42）：只存可审计的 query/evidence-summary/citations/answer，
   禁止 CoT；`FeedbackSanitizer` 做基础 secret redaction。
7. **非泛型 JsonlStore**：`model: type` + 调用方 `cast()`，规避 mypy 泛型推断问题。

### 3. 容器与入口

- `.local/feedback/`、`.local/review/`、`.local/flywheel/`（gitignored）。
- CLI：`submit_feedback.py` / `review_feedback.py` / `flywheel_report.py` / `promote_eval_case.py`，
  共享 `_flywheel_cli.py`；`run_agent.py --feedback` 让真人给每次回答打分。
- 架构边界：`flywheel/` 不 import LightRAG / adapter / provider SDK（新增架构守卫测试）。

## Alternatives Considered

### 自动在线学习 / 后台 auto-apply 提案

**拒绝且本项目禁止。** 违反旁路约束与安全边界：无人审核的自动改 Router/Prompt/知识库会引入
不可复现、不可审计的系统漂移。飞轮只产出"供人决策的证据"，应用永远走人工 + regression-gated。

### 建第二套 metric/trace 模型

**拒绝。** 复用 `AgentResult` / `Trace` / `EvalCase` / `MetricSummary` 已足够；飞轮作为消费者
绑定 `trace_id`，不复制运行时状态（spec §44/§45）。

### 用 LLM 生成 `flywheel_score` 或自动分类

**拒绝。** 违反"确定性、可解释"的既有原则；候选分类走确定性规则 A-E，review 分类走人工。

## Consequences

正面：
- 真实失败 / 反馈 / 缺口进入可追踪、可复现的改进通道；每个提案可溯源到
  candidate → feedback/trace → 运行时证据（audit trail，spec §37）。
- 回归门禁在应用任何改动前暴露质量回落，保护 37 例评测红线。
- 旁路设计保证学习路径完全不影响正常问答；架构守卫防止 flywheel 触碰 Kernel/provider。

代价 / 边界：
- 飞轮不自动改进任何东西——价值取决于"人工 + 数据质量"驱动，non-goal 明确：不是自动化学习引擎。
- 需要真实 provider 凭证跑集成验证（当前 DeepSeek 余额不足，integration 待充值后复跑；
  离线门禁不受影响）。

## When To Revisit

- 引入更大规模 / 多租户反馈时（可能需要真正的关系型 / DB 存储替代 JSONL）。
- 需求从"人类审阅提案"演进为"受控自动应用"时（必须新开 ADR，覆盖安全与回滚策略）。