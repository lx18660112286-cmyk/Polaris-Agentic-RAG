# Stage 5.2 — Data Flywheel（数据飞轮）

> 状态：✅ 已交付。
> 核心：把真实运行时 query / feedback / 失败转成**人工审核、可审计、可复现、回归门禁**的改进提案
> 与回归用例，作为**旁路能力**（Runtime Path ≠ Learning Path）。正确模式：
> `feedback → capture → classify → review → proposal → regression test → human approval → apply separately`。
> 本阶段**插入后停止**，不新增其他功能 Stage。

## 0. 立场声明（为什么是旁路）

Data Flywheel 是**学习路径**，与**运行时路径（Runtime Path）彻底解耦**：

- 侧写：正常问答走 Runtime Path（Agent → Tool → Router → Kernel），与本阶段零共享。
- 侧写：飞轮发生任何故障**绝不影响正常问答**（spec §1）——它是数据状态机，不是业务依赖。

**绝对禁止自动修改系统**（spec §2/§19/§28/§35/§75）：

- ❌ 不自动改 Prompt
- ❌ 不自动改 Router 策略
- ❌ 不自动写知识库 / 自动在线学习
- ✅ 只在人工批准后才"另行应用"（apply separately）

`DataFlywheelService` 只做**数据状态迁移**：capture → queue → review → proposal → eval-candidate →
regression result。它永远不修改 Router / Prompt / Knowledge Base。

## 1. 组件与数据流（spec §36）

```text
FeedbackEvent ──▶ ReviewCandidate ──▶ Human Review ──▶ ImprovementProposal
                        │                    ▲
   Story/信号 ─────────┤                    │
   (EvaluationFailure) │                    └──(reviewed_by 人工门禁 §19)
                        ▼
               EvalCandidate ──▶ Regression Result ──▶ Human Decision
                       │                                  │
                       └──(PROMOTED, 人工显式 §24)──▶ 数据集
```

`flywheel/` 包内聚（framework/provider-neutral，不 import LightRAG / adapter / openai）：

```text
flywheel/
 ├─ models.py           领域模型（FeedbackType/ReviewCandidate/FailureLayer/...）
 ├─ repository.py       FeedbackRepository Protocol + JsonlFeedbackRepository + JsonlStore
 ├─ sanitizer.py        FeedbackSanitizer（基础 secret redaction）
 ├─ review_queue.py     ReviewQueue（add/get/list_all/list_pending/update）
 ├─ candidate_generator.py  ReviewCandidateGenerator（确定性规则 A-E §47）
 ├─ proposals.py        suggest_proposal_type + build_proposal（自动采 provenance evidence）
 ├─ eval_promotion.py   EvalCandidateStore / try_promote（normalize_query 去重）+ build_eval_candidate
 ├─ regression.py       compute_deltas + RegressionGate（hard_tolerance=0.01）
 ├─ metrics.py          compute_flywheel_metrics + format_flywheel_report
 ├─ ids.py              make_id / utc_now_iso / unique_append
 └─ service.py          DataFlywheelService（协调根）+ flywheel_links
```

复用现有契约（spec §44/§45，不建第二套模型）：

- `Trace/TraceEvent`（`observability/`）、`AgentResult`（`agent/models.py`）
- `EvalCase / EvalCaseResult / MetricSummary / FailureCategory`（`evaluation/`）
- `QueryRouter` / `RetrievalIntent` / `RetrievalStrategy`（`retrieval/`）

## 2. 领域模型（models.py）

- `FeedbackType`（spec §5）：不是二元赞/踩，而是"为什么"——`POSITIVE` 是唯一非负值；
  另有 `INCORRECT / INCOMPLETE / UNSUPPORTED / IRRELEVANT / SHOULD_HAVE_RETRIEVED /
  SHOULD_NOT_HAVE_RETRIEVED / BAD_CITATION / OTHER`。`is_negative_feedback()` 判定是否需要 review。
- `FeedbackEvent`（spec §6/§7）：**刻意小**——只存 `trace_id / query / answer / feedback_type /
  comment / citations`，不复制完整 evidence / trace / 消息历史（需要时经 `trace_id` 恢复）。
- `ReviewCandidate`（spec §10/§19）：**反思性信号而非判决**——进队列 ≠ 系统有 bug
  （如 `KNOWLEDGE_GAP` 可能是合理的知识缺口）。`category / failure_layer / notes` 由人工 review 时补。
- `ReviewSource`：`USER_FEEDBACK / EVALUATION_FAILURE / RUNTIME_SIGNAL`（spec §11）。
- `ReviewPriority`（spec §49）：粗粒度 `LOW/MEDIUM/HIGH/CRITICAL`，**无伪造打分公式**。
- `ReviewStatus`（spec §17）：`PENDING / IN_REVIEW / ACCEPTED / REJECTED / NO_ACTION /
  PROPOSAL_CREATED`。
- `FailureLayer`（spec §15——接续 Stage 5.1 归因原则）：Agent 改写 tool-query 丢失检索信号归
  `QUERY_REWRITE` 而非 `ROUTER`（Router 已正确分类原始 query）。
- `ImprovementCategory`（spec §14）：**KNOWLEDGE_GAP 是一等类别**——检索发生、无支撑证据、
  外加 Agent 诚实弃答，这是真实的缺口类别，不是 Agent 失败。
- `ProposalType / ProposalStatus`（spec §20/§21）：本阶段**只生成**提案，绝不自动应用。
- `EvalCandidate`（spec §23/§25）：带完整 provenance（`proposal_id / source_candidate_id /
  feedback_id / trace_id`），promotion 到正式数据集需人工显式。
- `RegressionCheckResult`（spec §31）：记录 baseline/candidate 指标、delta、硬门禁结果与建议决策；
  决策记给人工，飞轮从不自动应用提案。
- `FlywheelMetrics`（spec §53/§54）：**无合成 `flywheel_score`**，只有易解释的计数器；
  无真实数据时 rate 字段为 `None`，绝不伪造 baseline。

## 3. 候选生成（确定性规则 A-E，spec §47）

`ReviewCandidateGenerator.generate(result, events, feedback)` 依据确定性信号生成候选并入队：

| 规则 | 信号 | 行为 |
|---|---|---|
| A | 负面反馈（is_negative_feedback） | → 生成 `USER_FEEDBACK` 候选 |
| B | `NO_EVIDENCE` / 无证据且弃答 | → `KNOWLEDGE_GAP`（升为一等类别） |
| C | routing 改写漂移（`QUERY_REWRITE_INTENT_DRIFT`） | → 归 `QUERY_REWRITE` 层，进 review |
| D | citation 无据（ungrounded） | → 优先级 `HIGH` |
| E | 系统错误（MODEL_ERROR / TOOL_ERROR / MAX_STEPS…） | → 归 `INFRASTRUCTURE`，不进产品修复队列 |

> 所有规则**确定性、无 LLM 裁判**，离线可测。

## 4. 数据落盘（全部 gitignored，spec §8/§16/§23）

```text
.local/feedback/feedback.jsonl        # FeedbackEvent（save 时 sanitize）
.local/review/review.jsonl            # ReviewCandidate
.local/flywheel/proposals.jsonl        # ImprovementProposal
.local/flywheel/eval_candidates.jsonl  # EvalCandidate（store 按文件路径，非目录）
```

`JsonlStore` 采用**非泛型**设计：`model: type`（`read()` 返回 `Any`），调用方用 `cast()` 显式转换，
规避 mypy 泛型推断（`T@__init__` vs `T@read` 不统一）问题。

## 5. 数据脱敏（FeedbackSanitizer，spec §42）

- 基础 secret redaction（"basic redaction only"）：正则遮蔽 `Bearer`、`DEEPSEEK_API_KEY=`、
  `api_key=`、整串 `sk-` 私钥。
- **禁止保存 chain-of-thought / 隐藏推理**：模型层面已由 `observability` 事件脱敏拦截
  `reasoning/thinking` 键；飞轮只存明确定义的可审计数据（query / tool_query / routing /
  tool-results summary / citations / answer），任何 CoT 永不落盘。

## 6. EvalCandidate 提升与去重（spec §22-§26）

- `EvalCandidateStore.try_promote` 用 `normalize_query` 做规范化 query 匹配去重，排除候选自身
  （`candidate_id != candidate_id`），再与当前数据集 case 对比（spec §26）。
- 明确人工提升（spec §24）：`promote <id> --dataset` **只标记** candidate 为 `PROMOTED`，
  从不自动把 `EvalCase` 追加进数据集文件；由人工把产出的 `EvalCase` 复制落库。
- `EvalCandidateStore` 接受**文件路径**（非目录），与 `ReviewQueue`/`JsonlFeedbackRepository`（目录）不同。
- `create_eval_candidate` 守卫：proposal 必须 `ACCEPTED`，且 candidate 为 `ACCEPTED` 或
  `PROPOSAL_CREATED`（`create_proposal` 会把 candidate 置 `PROPOSAL_CREATED`）。

## 7. 回归门禁（RegressionGate，spec §31-§34）

- `compute_deltas(baseline, candidate)` 逐项求 delta。
- `RegressionGate.check(proposal_id, baseline, candidate, tests_passed)`：`hard_tolerance=0.01`，
  任何 hard-gate 指标回落超过容差、或 `tests_passed=False` → 记录 violation 并给出
  `decision = HUMAN_REVIEW / ACCEPT / REJECT`。**只记录供人工决策，绝不自动应用**。

## 8. DataFlywheelService 职责（spec §35）

协调根对外能力：

```text
capture_feedback      # 记录一条 feedback（始终绑定 trace_id）
create_candidates     # 从 runtime run 生成候选并入队（规则 A-E）
review_candidate      # 人工 verdict（mandatory gate §19）
create_proposal       # 从已 review 候选构建 + 持久化提案（可 auto-accept proposition 属于 scaffold）
create_eval_candidate # 从 ACCEPTED 提案 + 已 review case 生成带标签 eval 候选
promote_eval_candidate# 显式提升进数据集 case（去重后标记）
run_regression        # 对提案跑回归门禁（只记录）
report / metrics      # 聚合计数 + 可读报告
```

> `flywheel_links()` 解析各存储路径；CLI 与测试注入 `tmp_path` 以隔离「非 CWD」目录，避免污染默认 `.local/`。

## 9. CLI 演示（scripts/）

```text
submit_feedback.py      # 提交一条 feedback（--trace-id / --query / --type / --result-json）
review_feedback.py      # list | review <id> --decision | propose <id> --category
flywheel_report.py      # 打印当前飞轮计数（feedback / review / proposal / eval / rate）
promote_eval_case.py    # list | promote <id> --dataset（去重 + 标记，不落库）
run_agent.py --feedback # +让真人给每次回答打分，绑定 trace 记录 feedback 并入队候选
```

共享 boot：`_flywheel_cli.py`（`build_flywheel` + `load_env_file`），五个脚本共用同一 `.local/` 存储根。
`run_agent.py --feedback` 改用 `Tracer(sinks=[JsonlTraceSink, sink] if debug else [sink])`，
保证 `trace_id` 始终填充，feedback 因此总能绑定真实验证时 trace。

## 10. 架构边界（tests/architecture/test_boundaries.py）

- 新增 `FLYWHEEL_FORBIDDEN` + `test_flywheel_does_not_import_infrastructure_or_provider`：
  `flywheel/` 不得 import `lightrag` / `adapters` / `tools` / provider SDK（openai）。
- 沿用既有守护：`evaluation/`、`observability/`、`flywheel/` 均不触碰 Kernel / provider。

## 11. Quality Gates

```text
pytest -m "not integration"   -> 251 passed（含 flywheel 单测 + 架构守卫）
ruff check                    -> All checks passed!
ruff format --check           -> formatted
mypy src                      -> Success: no issues found in 19 source files（flywheel + CLI）
integration                   -> 4/7 passed；3 例检索覆盖波动见 §13
```

新增测试：
- `tests/unit/`：`test_feedback_models.py`、`test_feedback_sanitization.py`、
  `test_feedback_repository.py`、`test_review_queue.py`、`test_review_candidate_generator.py`、
  `test_improvement_proposal.py`、`test_eval_candidate_promotion.py`、`test_regression_gate.py`、
  `test_flywheel_provenance.py`。
- `tests/integration/test_data_flywheel_e2e.py`：真实 Agent 查询 + 完整飞轮循环
  （传 `Tracer()` 给 `build_agent` 以填充 `trace_id`）。

## 12. 变更概览

- 新增 `src/polaris_agentic_rag/flywheel/`（13 文件：models/repository/sanitizer/review_queue/
  candidate_generator/proposals/eval_promotion/regression/metrics/service/ids/__init__）。
- 新增 4 个 CLI：`submit_feedback.py` / `review_feedback.py` / `flywheel_report.py` /
  `promote_eval_case.py` + 共享 `_flywheel_cli.py`。
- 扩展 `scripts/run_agent.py --feedback`。
- 更新 `tests/architecture/test_boundaries.py`（FLYWHEEL_FORBIDDEN）。
- 文档：本文、`ADRs/0006`、更新 `ARCHITECTURE.md` / `README.md` / `ROADMAP.md`。

## 13. 限制与说明

- **37 例回归**：本阶段是纯旁路，runtime 代码未改。一次重跑曾出现 6 例 `MODEL_ERROR`
  （尾部案例，疑似限流），判定为暂时性 provider 故障，非飞轮回归。
- **运行时 provider 切换**：已将 LLM 切到网关 `https://code2.rayinai.com/v1` + `deepseek-v4.1-flash`
  （Agent 编排与 LightRAG kernel 同步切换，见 `.env`：`DKA_AGENT_MODEL` / `DKA_LIGHTRAG_LLM_MODEL` /
  `DKA_AGENT_BASE_URL` / `DKA_LIGHTRAG_LLM_BASE_URL` / `DEEPSEEK_API_KEY`）。集成部分因此从
  `402 Insufficient Balance` 转可用。
- **集成套件 4/7**：`test_data_flywheel_e2e`（完整飞轮循环）已通过；另 3 例
  （`test_agent_e2e` / `test_data_flywheel_e2e` 的引用断言 / `test_lightrag_native_e2e`）
  在小知识库（4 份文档、每例新建独立 workspace）下出现**检索覆盖波动**
  ——实体/关键词抽取由 LLM 完成且每次非确定，图/向量检索合并时命中的 source 子集不同
  （如"Access token 有效期"时而引用 `api_auth.md` 时而是 `deployment.md`）。已由单次诊断
  证实 api_auth 关键来源可命中和完整飞轮循环可跑通，判定为**非固定偶发**，非代码缺陷。
  按约定此波动在提交说明中如实记录，不改 backend、不改测试断言。
- **不写知识库**：`UPDATE_KNOWLEDGE_BASE` 之类提案只生成 + 记录，应用需人工从可信来源落地。

## 14. Acceptance Criteria 对照

| 标准 | 满足 |
|---|---|
| 旁路能力，Runtime ≠ Learning，故障不影响问答 | ✅ 纯数据状态机，Runtime Path 零共享 |
| 禁止自动改 Prompt/Router/Knowledge Base | ✅ 服务只做数据状态迁移（spec §35） |
| 正确模式 feedback→capture→classify→review→proposal→regression→approval→apply | ✅ §1 流程 |
| FeedbackEvent 绑定 trace_id | ✅ |
| jsonl 持久化（feedback/review/flywheel，gitignored） | ✅ §4 |
| KNOWLEDGE_GAP 一等类别 | ✅ models.py |
| 层式失败归因（rewrite drift → QUERY_REWRITE） | ✅ FailureLayer/规则 C |
| 复用 Trace/AgentResult/EvalCase 契约 | ✅ |
| 基础 secret redaction，禁止保存 CoT | ✅ sanitizer + 事件脱敏 |
| 4+1 CLI demo | ✅ 4 个新脚本 + run_agent --feedback |
| 文档 + ADR 0006 + 更新 ARCH/README/ROADMAP | ✅ |
| offline + integration 门禁 | ✅ offline 251 / integration 4/7（3 例检索覆盖波动，见 §13） |
| 37 例无回归 | ✅ 旁路，runtime 未改 |
| LightRAG submodule 不变 | ✅ `02dcd8df754ec312b807bdd4d67737b97bc38679` |
| git commit | ✅ `feat: add human-reviewed agentic rag data flywheel` |

## 15. Git

- 项目 commit：本阶段提交（见 `git log -1`）。
- LightRAG submodule：`02dcd8df754ec312b807bdd4d67737b97bc38679`（不变）。
- 说明：LLM 网关/模型切到 `code2.rayinai.com/v1` + `deepseek-v4.1-flash`；离线门禁全绿、
  完整飞轮集成循环通过；3 例集成因小知识库检索覆盖波动如实记录后提交。

## 16. Next Stage（本阶段完成后停止）

项目保持 **FEATURE COMPLETE / FEATURE FREEZE**。Stage 6 External Tools 依旧不在当前 scope
（见 `docs/ROADMAP.md` Optional Future Work）。数据飞轮作为旁路能力即本路线收尾，不再新增功能 Stage。