# Stage 3 — Retrieval Strategy + Query Router

> 目标：让"如何检索"成为应用层可解释、可测试、可调优的策略，而不是 Kernel 固定配置。
> Agent / Caller 仍然只提供 `query`；`mode / top_k / rerank` 由 Router 内部决定。

## 1. 为什么需要 Routing

Stage 2 把检索参数藏在 `LightRAGAdapterSettings`（默认统一 `hybrid`）。但 Stage 1 观察显示
不同用户意图倾向于不同检索形态：

- **local** → 实体级聚焦召回（精确事实）
- **global** → 概览 / 关系级（系统全局）
- **hybrid** → 图 + chunk 综合（跨文档、关系/排查）
- **naive** → 纯向量
- **mix** → 图 + 向量联合

把"如何检索"交给一个确定性 Router，可以让每个意图独立调优、可解释、可离线测试，并为
Stage 5 Evaluation / Tracing 提供稳定基线。

## 2. RetrievalIntent（为什么要这么问）

```python
class RetrievalIntent(str, Enum):
    FACTUAL        # 精确事实 / 数值
    TERMINOLOGY    # 术语 / 错误码定义
    RELATIONAL     # 依赖 / 关系
    MULTI_DOCUMENT # 跨文档的运维/排查任务
    OVERVIEW       # 系统整体 / 架构概览
    GENERAL        # 不明确 → 安全回退
```

小、确定性、可解释；不追求过细分类（spec §5）。

## 3. RetrievalStrategy（应用自有策略）

```python
class RetrievalStrategy(str, Enum):
    FOCUSED = "focused"   # 明确实体 / 精确事实 / 局部知识
    GLOBAL  = "global"    # 系统概览 / 高层关系 / 全局问题
    HYBRID  = "hybrid"    # 图结构 + chunk 综合
    VECTOR  = "vector"    # 纯语义向量
    MIXED   = "mixed"     # 图 + 向量联合
```

这是 **application-owned strategy**，不是 LightRAG 类型。

## 4. RetrievalPlan

```python
class RetrievalPlan(BaseModel):
    intent: RetrievalIntent
    strategy: RetrievalStrategy
    top_k: int
    chunk_top_k: int | None = None
    enable_rerank: bool = False
    reason: str
```

禁止出现 `QueryParam` / `LightRAG` 等 vendor 类型。

## 5. Routing Rules（`retrieval/rules.py`）

管线：`QueryFeatures → decide_intent → RetrievalStrategy`。优先顺序（最具体在前）：

```text
OVERVIEW > TERMINOLOGY > RELATIONAL > MULTI_DOCUMENT > FACTUAL > GENERAL
```

有限、有限的 marker 集合（非 keyword soup），以及可解释的 reason。

| 意图 | 命中线索（示例） | 策略 |
|---|---|---|
| FACTUAL | "有效期是多少"、"有什么区别" | FOCUSED |
| TERMINOLOGY | 全大写错误码(如 `DB_CONNECTION_POOL_EXHAUSTED`) + "是什么意思" | FOCUSED |
| RELATIONAL | "依赖哪些"、"有什么关系" | HYBRID |
| MULTI_DOCUMENT | "如何定位问题"+"判断是否回滚" 等运维措辞 | HYBRID |
| OVERVIEW | "整个系统"、"核心组件和关系" | GLOBAL |
| GENERAL | 无明确线索 → 显式回退 | HYBRID |

## 6. Fallback 策略

Router 是确定性、无网络、无 LLM 的，正常不应失败。万一因意外错误无法 route：

- 不直接让 Tool 不可用；
- 返回安全默认 `RetrievalPlan`（GENERAL → HYBRID）；
- 通过 `RoutingDecision.fallback_used=True` 显式记录，并在 `RagSearchResult.routing` 透出；
- **禁止 silent fallback。**

## 7. LightRAG 映射（只在 Adapter 内）

```python
# adapters/lightrag/adapter.py :: _STRATEGY_TO_MODE
FOCUSED → "local"
GLOBAL  → "global"
HYBRID  → "hybrid"
VECTOR  → "naive"
MIXED   → "mix"
```

只有 `adapters/lightrag/` 知道真实 mode 字符串；Router / Tool / protocols 绝不触碰。

## 8. RagSearchTool 变化

```text
Stage 2: invoke(query) → search_port.search(query)
Stage 3: invoke(query) → router.route(query) → plan → search_port.search(query, plan)
```

- 输入仍然只有 `query`（`RagSearchInput`），**禁止**增加 strategy/mode/top_k 等 Agent-facing 参数。
- `__init__(search_port, *, router)`：Tool 依赖 Port + Router，二者都可被 fake 注入。
- `RagSearchResult.routing: RoutingDecision | None` 用于调试 / 测试 / 观测。

## 9. Port 变化

```text
Stage 2: async search(query: str)                       -> KnowledgeSearchResult
Stage 3: async search(query, *, plan: RetrievalPlan | None = None) -> KnowledgeSearchResult
```

`plan=None` 时 Adapter 用默认策略；Tool 正常路径始终传 Router 生成的 plan。

## 10. Evidence Contract 变化

- 移除 `RetrievalDiagnostics.query_mode`（vendor 诊断泄漏）。
- Agent/application-facing 用 `RetrievalStrategy` / `RetrievalIntent`，真实 LightRAG `mode`
  只存在于 Adapter 内部或 internal debug logging。
- 其余（Evidence / Citation / EntityEvidence / RelationshipEvidence / ChunkEvidence / SourceResolver）不变。

## 11. Routing Dataset（`tests/fixtures/routing_cases.json`）

基于 `stage1_queries.json` 建立，覆盖 6 类 intent，每个 case 指定 expected intent + strategy。

## 12. 测试矩阵（Stage 3）

| 测试 | 覆盖 |
|---|---|
| `tests/unit/test_query_router.py` | 6 类 intent + GENERAL 回退 + 确定性 + fallback 可观测 |
| `tests/unit/test_retrieval_plan.py` | plan 字段、无 vendor 泄漏、strategy/intent 枚举边界 |
| `tests/unit/test_lightrag_adapter.py` | `RetrievalStrategy → QueryParam.mode` 映射 + plan=None 默认 |
| `tests/unit/test_rag_search_tool.py` | Tool 只依赖 Port + Router；plan 被转发；routing 透出 |
| `tests/unit/test_knowledge_search_contract.py` | Port 新签名 `(query, *, plan)` 不含 vendor 类型 |
| `tests/unit/test_lightrag_result_mapper.py` | 移除 query_mode 后映射仍一致 |
| `tests/architecture/test_boundaries.py` | `retrieval/` 禁 import lightrag/adapters/tools/agent |
| `tests/integration/test_routed_rag_search_e2e.py` | 真实 Kernel：factual→FOCUSED、multi-doc→HYBRID，证据+citation 成功 |

## 13. Quality Gates（真实结果）

```text
pytest -m "not integration"   # 50 项全绿（Stage 2 36 + 架构/契约/路由 等）
pytest -m integration         # 4 项全绿（真实 Kernel：native + tool + routed）
ruff check src tests          # All checks passed
ruff format --check src tests # 41 files already formatted
mypy src                      # Success: no issues found in 27 source files
architecture guard            # passed
```

## 14. Minimal Routing Evaluation（不是完整 benchmark）

Stage 3 只做 sanity：记录 `query / intent / strategy / evidence count / citations`，
确认 Router 未明显降低 Stage 1 已通过问题的检索能力；真实 E2E 里 factual 与 multi-document
两条都得到 SUCCESS + evidence + citations。完整 Evaluation 属于 Stage 5。

## 15. Limitations

- 规则基于当前 KB 的措辞设计；换领域需重写 `retrieval/rules.py` 的 marker 集合。
- 未引入 LLM Router（有意延迟，见 ADR 0003 §Alternatives B）。
- rerank 未配置，`enable_rerank` 恒为 `False`；未来 Evaluation 后再决定。
- latency 受 llm_response_cache 影响（同 Stage 1）。

## 16. Stage 4 Implications

Stage 3 为 Stage 4 铺路：`RagSearchTool` 已成为"带内部路由决策的检索工具"，`routing` 可被
Agent / Tool Registry / Tracing 消费。Stage 4 将引入 Agentic RAG Orchestrator（Retrieval
Invocation / native function calling / Grounded Synthesis）与 `RagSearchTool` 调用，但**不再改**
Tool 的 `query` 输入形态与 Retrieval/Routing 语义。

---
更新时机：本报告随 pinned commit 与真实运行结果更新；若 kernel 升级改变 `aquery_data` 结构或
去重语义，需重跑 baseline / 集成测试并更新本文件。