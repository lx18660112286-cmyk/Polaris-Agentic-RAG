# Stage 1 — LightRAG Native E2E Baseline

> 目标：绕过 Agent / RagSearchTool / Query Router，直接验证 pinned LightRAG Kernel
> 在本项目知识库上的真实 E2E 行为。本报告所有结论均来自**真实运行结果**，
> 结构化观测数据见 `.local/lightrag_stage1/baseline_results.json`（gitignored）。

## 1. Pinned Commit 与 Provider

| 项 | 值 |
|---|---|
| Pinned commit | `02dcd8df754ec312b807bdd4d67737b97bc38679`（main） |
| LLM provider | DeepSeek（OpenAI 兼容，`lightrag.llm.openai.openai_complete_if_cache`） |
| LLM model | `deepseek-chat` |
| Embedding provider | Ollama 本地（`lightrag.llm.ollama.ollama_embed`） |
| Embedding model | `bge-m3:latest`（1024 dim，本地已拉取） |
| Rerank | **未配置** → `Rerank baseline not executed`（无 rerank provider，不 fake） |
| Working dir | `.local/lightrag_stage1/`（gitignored，独立于 integration 临时目录） |

**凭据策略**：`DEEPSEEK_API_KEY` 只存在于本地 gitignored `.env`，未提交、未出现在任何输出中。

## 2. Storage Lifecycle

```text
construct LightRAG → initialize_storages() → ingest → query/aquery_data → finalize_storages()
```

- `initialize_storages()`：文件后端初始化 < 0.1s，成功。
- `finalize_storages()`：每次运行经 `try/finally` 保证执行，日志确认 "Successfully finalized 12 storages"。
- 生成的 storage 文件（gitignored）：`kv_store_*.json`（text_chunks / full_entities / full_relations / llm_response_cache / doc_status 等）、`vdb_*.json`（nano-vectordb）、`graph_chunk_entity_relation.graphml`。

## 3. Ingestion

| 项 | 结果 |
|---|---|
| Documents | 4（deployment / api_auth / incident_runbook / service_overview） |
| API | `ainsert(contents, file_paths=[真实绝对路径])` |
| 首次 ingest 耗时 | **37.18s**（真实 entity/relation 抽取 + bge-m3 embedding） |
| 二次 ingest（同一批路径） | **0.01s**，自动去重 |
| doc status | 4 份 `processed` |
| Duplicate 行为 | 相同文件重复提交生成 `dup-*` id 且标记 **`failed`**（LightRAG 的 duplicate 分类，写入 doc_status） |
| Chunk 情况 | 4 个 chunk（每个 md ≤ 1 个 chunk，与默认 chunk_token_size 相符），图含 89 nodes / 92 edges，vdb 89 entities / 92 relations / 4 chunks |

**不要假定 ingestion success = retrieval success**：ingest 成功仅是入图，检索质量另验证（见第 5 节）。

## 4. Baseline Questions（Case A-H，hybrid mode）

| Case | 类型 | 回答 | 引用 sources | 结论 |
|---|---|---|---|---|
| A | simple fact（token 有效期） | ✅ 「30 分钟」 | 4 文件（api_auth 为主） | 正确 |
| B | exact terminology（DB_CONNECTION_POOL_EXHAUSTED） | ✅ 含义+处理 | 4 文件 | 正确，术语命中 |
| C | deployment（回滚） | ✅ 回滚流程+触发条件 | 4 文件 | 正确 |
| D | multi-document（5xx 定位+回滚判断） | ✅ 定位步骤+决策条件 | 4 文件 | 正确，跨文档 |
| E | relationship（依赖+排查作用） | ✅ 组件逐个展开 | 4 文件 | 正确，关系抽取有效 |
| F | authentication（401/403+刷新） | ✅ 对比+流程 | 4 文件 | 正确 |
| G | unanswerable（Billing Service 数据库） | ✅ **"I don't have enough information"** | 4 文件 | **未幻觉** |
| H | insufficient evidence（DR 步骤 + RPO/RTO） | ✅ **"无法给出完整方案"，并列出已有线索** | 4 文件 | **未幻觉补全** |

要点：
- A-H 全部真实作答，耗时 3.5–4.9s/条。
- **G/H 都诚实承认信息不足，没有编造确定答案** —— pinned Kernel 在原样（hybrid + top_k=20）下具备"拒绝幻觉"的基础表现，但这是当前配置下的观察，不是保证。
- 每条返回 4 个 references（file 级），即**检索上下文天然横跨全部 4 份文档**（top_k=20 的实体级召回面较宽），Source 定位粒度是「文件」而非「段落」。

## 5. Query Mode Comparison

代表性问题 × 5 modes（local / global / hybrid / naive / mix），3 个 query 各跑一遍（n=3/mode）：

| Mode | answered | avg latency | entities | relationships | chunks | refs | 备注 |
|---|---|---|---|---|---|---|---|
| local | 3/3 | 4.69s | 20 | 30–36 | 3–4 | 11 | 实体级聚焦召回 |
| global | 3/3 | 4.97s | 20–26 | 20–30 | 4 | 12 | 关系/概览级 |
| hybrid | 3/3 | **0.75s** | 30–37 | 34–51 | 4 | 12 | 本组前序 hybrid 已跑过（LLM cache 命中） |
| naive | 3/3 | 3.10s | 0 | 0 | 4 | 12 | 纯向量：entities/relationships 为空（设计如此） |
| mix | 3/3 | 4.49s | 28–44 | 33–50 | 4 | 12 | 图+向量，量最大 |

观察（仅记录，Stage 3 才编码 routing policy）：
- **naive 明确返回 entities/relationships 数组为空**——符合 source 文档说明，不能给 Tool 提供"证据图"。
- hybrid/mix 的实体+关系召回量最大，适合跨文档/关系类问题；local 召回更聚焦。
- latency 首跑 ~4.5–5s，hybrid 复跑 0.75s 是 llm_response_cache 命中，**注意 cache 对延迟测量有污染**。
- 5 种 mode 都能给出可用答案；本知识库规模小，mode 间质量差异主要体现为检索结构的差异而非对错。

## 6. aquery_data（Stage 1 重点）

h```hybrid, Case A 的真实返回（已 sanitize）：

```json
{
  "status": "success",
  "message": "...",
  "data": {
    "entities": [{"entity_name": "refresh token",
                  "entity_type": "data",
                  "description": "A token issued by the Auth Service ...",
                  "source_id": "doc-xxx-chunk-000",
                  "file_path": "service_overview.md", "created_at": "..."}],
    "relationships": [{"src_id": "API Gateway", "tgt_id": "Order Service",
                       "description": "...", "keywords": "Request Routing",
                       "weight": "1.0", "source_id": "doc-xxx-chunk-000",
                       "file_path": "service_overview.md", "created_at": "..."}],
    "chunks": [{"reference_id": "1", "content": "# Authentication & API Access ...",
                "file_path": "api_auth.md", "chunk_id": "doc-yyy-chunk-000"}],
    "references": [{"reference_id": "1", "file_path": "api_auth.md"}, ...]
  },
  "metadata": {
    "query_mode": "hybrid",
    "keywords": {"high_level": ["access token", "token expiration"],
                 "low_level": ["access token", "有效期"]},
    "processing_info": {"total_entities_found": 30, "total_relations_found": 34,
                        "entities_after_truncation": 30, "relations_after_truncation": 34,
                        "merged_chunks_count": 4, "final_chunks_count": 4}
  }
}
```

关键结构事实：
- 顶层 `status/message/data/metadata`；查询级失败时 `status="failure"`。
- `data.entities / relationships / chunks / references` 四段齐备（naive 模式 entities/relationships 为空）。
- `reference_id` 在 **chunks 与 references 之间直接关联**（chunk 引 `reference_id`，references 表给出 `file_path`）。
- `metadata.processing_info` 给出截断前后数量——可直接用于"证据是否被截断/不足"的判断线索。
- 未修改 LightRAG 原始结构。

## 7. References

| 验证点 | 结果 |
|---|---|
| reference 是否存在 | 是（每 query ≥ 11 条 ref 记录） |
| reference_id 是否稳定 | 是（`"1".."4"` 数字 id，chunk 内引用一致） |
| file_path 是否指回 KB | 是，但**只存 basename**（`api_auth.md`，无目录前缀） |
| chunk ↔ reference 关联 | 是（chunk.reference_id → references[].reference_id） |
| 多文档 query 多 source | 是（Case D/E 返回 ≥2 个 source 文件） |
| missing reference 行为 | 未在本次触发（无法无成本构造），留待 Stage 2 主动探测 |

> **重要发现（Stage 2 设计输入）**：`file_path` 被 Kernel 归一化为 **basename**。若 Evidence 需要还原完整路径，Adapter 必须自行维护「basename → 原始路径」映射（例如 ingest 时记录文件名映射），不能依赖 Kernel 返回全路径。

## 8. Unknown / Insufficient Evidence（幻觉风险）

- **Case G（Billing Service）**：回答 "I don't have enough information to answer that question."，并列出知识库实际存在的组件（Mercury 平台）——**未虚构 Billing 的数据库**。
- **Case H（DR 步骤/RPO/RTO）**：回答 "无法给出生产数据库完整的灾难恢复步骤和 RPO/RTO"，随后列出知识库中存在的相关线索（发布检查清单、`ORDER_DB_DSN`、回滚触发条件）——**区分了"有相关证据"与"证据不足"**。
- 结论：当前配置（hybrid + top_k=20 + deepseek-chat）下 Kernel 对未知/证据不足问题表现出良好的"拒绝作答"倾向；但**这不是 guardrail**，Stage 1 按规范不做任何 hallucination guard，Guardrail 属于 Layer 层（Tool/Agent）。

## 9. Failure Behavior（真实 failure shape）

| 场景 | 真实异常/形态 |
|---|---|
| 空 query | `EmptyQueryError: Query must not be empty.`（LightRAG 自带异常类） |
| 非法 mode | `ValueError: Unknown mode not_a_mode` |
| 未 initialize 即 query | `TypeError: 'NoneType' object does not support the asynchronous context manager protocol`（**与文档预期的 `StorageNotInitializedError` 不同**——pinned 源码实际先崩在这里；记录差异） |
| 生命周期错误位置 | `aquery` 起点校验/存储访问路径，非 LLM 层 |

## 10. Limitations

- 本报告是**单实例单日观察**：一次 ingest、一组 query、一个 model；非统计评估。
- `latency` 受 llm_response_cache 影响，首跑/复跑差异大。
- 涉及 network/LLM 的集成测试在无凭据环境自动 skip（credential-aware）。
- Rerank baseline 未执行（无 rerank provider）。
- knowledge base 很小（4 个短文档 → 4 chunks），模式间差异更多体现在结构而非质量上。
- `enable_rerank=True` 在未配置 rerank model 时会打 warning 并可能影响结果——本次未开启。

## 11. Implications for Stage 2

> 基于真实 E2E 观察，仅讨论，不实现。

### A. RagSearchTool 至少需要返回什么

- 归一化后必须至少包含：**answer（生成回答）+ evidence（检索证据）+ citation（文件级引用）**。
- 每条 evidence 至少：`file_path(basename) + chunk_id + reference_id + entity/relation 概述`。
- 必须携带**证据充分性信号**：是否 `status=failure`、entities/relationships/chunks 是否为空、`processing_info` 截断前后数量（判断"证据被截断"）。
- tool result 需要显式的 `insufficient_evidence` 表达——绝不能把 Kernel 的 empty/naive 空数组默默透传成"没有答案"。

### B. Evidence Contract 至少承载什么

- source（文件名）→ 需要 **basename→原始路径映射**（Kernel 只给 basename）。
- chunk（content + chunk_id + reference_id）。
- entity（entity_name/type/description、source_id）。
- relationship（src/tgt/description/keywords/weight）。
- reference_id：作为 chunk↔引用↔文件名之间的关联键。

### C. LightRAGAdapter 要隐藏哪些 vendor details

- `QueryParam`（构造与字段语义）——Tool 层不暴露。
- `mode` / `top_k` / `chunk_top_k` / `enable_rerank`——由 Retrieval Strategy 内部决定。
- 真实检索返回结构（`data.entities/...` 的嵌套 dict）。
- 真实 failure shape（`EmptyQueryError` / `ValueError(Unknown mode)` / `TypeError(NoneType)` 等各类异常 → 映射为统一 ToolError 语义）。
- `include_references` 等开关。
- LLM/embedding/rerank provider 函数注入细节。

### D. 哪些 LightRAG 能力应该被保留

- `aquery_data`（结构化检索 + metadata + reference 关联）——Evidence 的主要来源。
- `aquery`（最终回答生成），与 aquery_data 配对使用。
- references / reference_id 关联机制——citation 的天然基础。
- `metadata.processing_info`（截断前后计数）——证据充分性信号。
- mode 语义（local 聚焦实体 / global 概览 / naive 纯向量 / hybrid+mix 组合）——Routing 的候选参数（Stage 3 再编码策略）。
- doc dedup / duplicate 标记（`dup-*` + `failed`）——ingest 层可复用的幂等能力。

---
更新时机：本报告随 pinned commit 与真实运行结果更新；若 provider/model 或 kernel 升级导致行为变化，需重跑 baseline 并更新本文件。