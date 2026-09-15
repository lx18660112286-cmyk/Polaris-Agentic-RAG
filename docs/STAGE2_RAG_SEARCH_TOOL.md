# Stage 2 — RagSearchTool + KnowledgeSearchPort + Evidence Contract

> 目标：把 Stage 1 验证过的 RAG Kernel（LightRAG）包装成一个稳定、框架无关、
> Agent 可直接使用的 Tool。本阶段不实现 Quant Retrieval Router / RetrievalPlan
> （那是 Stage 3），也不引入 Agent（那是 Stage 4）。

## 1. 设计输入（来自 Stage 1 真实观察）

Stage 1 的 baseline 证明 pinned Kernel 的 `aquery_data` 返回固定结构：

```json
{
  "status": "success" | "failure",
  "message": "...",
  "data": {
    "entities":      [{"entity_name", "entity_type", "description", "source_id", "file_path", ...}],
    "relationships": [{"src_id", "tgt_id", "description", "keywords", "weight", "file_path", ...}],
    "chunks":        [{"reference_id", "content", "file_path", "chunk_id"}],
    "references":    [{"reference_id", "file_path"}]
  },
  "metadata": {
    "query_mode": "hybrid",
    "keywords": {"high_level": [...], "low_level": [...]},
    "processing_info": {"total_entities_found", "entities_after_truncation", "final_chunks_count", ...}
  }
}
```

直接决定了本阶段的三个关键取舍：

1. **不能让 Agent 吃到这些嵌套 dict** → 定义自己的 Evidence Contract（纯 Pydantic，无 LightRAG 类型）。
2. **`file_path` 只剩 basename** → 需要 `SourceResolver` 做 basename → 路径还原，且要处理
   唯一 / 缺失 / 歧义三种情况，绝不静默挑一个。
3. **failure 形态多样**（`EmptyQueryError`、`ValueError: Unknown mode`、`TypeError(NoneType)`、
   `status="failure"`）→ 需要一个异常归一化边界，把 vendor-specific 失败压成领域异常。

## 2. 交付的架构

```text
RagSearchTool
     │  depends on
     ▼
KnowledgeSearchPort (Protocol)
     ▲  implements
     │
LightRAGAdapter
     ├─ build_lightrag(working_dir, workspace=...) → LightRAG
     ├─ SourceResolver               (basename → 路径)
     ├─ map_query_data_to_result()   (raw dict → 领域模型，纯函数)
     └─ normalize exceptions → evidence.errors.*
     │
     ▼
LightRAG <-> storage (kv / vdb / graphml / doc_status)
```

### 依赖方向（受 `tests/architecture/test_boundaries.py` 强制）

- 生产代码中只有 `adapters/lightrag/` 允许 import LightRAG（AST guard）。
- `tools/` 不得 import `adapters/` — Tool 只依赖 Port。
- `protocols/` 不得 import `adapters/` / `tools/` / `agent/`。
- `evidence/` 不得 import LightRAG / adapters / tools / agent（纯领域层）。

## 3. Evidence Contract（`evidence/models.py` + `evidence/errors.py`）

框架无关的领域模型，字段形状扎根于 Stage 1 真实 payload；字段缺失保持 `None`，不伪造。

| 模型 | 作用 |
|---|---|
| `KnowledgeSearchResult` | Port 层结果：`query / evidence / citations / diagnostics / evidence_availability`（`extra="forbid"`） |
| `Evidence` | `chunks / entities / relationships` 三段 |
| `ChunkEvidence` | `chunk_id / content / reference_id / source_name / source_path` |
| `EntityEvidence` | `entity_name / entity_type / description / source_id / file_path / reference_id / ...` |
| `RelationshipEvidence` | `src_id / tgt_id / description / keywords / weight / ...` |
| `Citation` | `reference_id / source_name / source_path / source_resolution` |
| `RetrievalDiagnostics` | `query_mode / keywords / 各类计数 / processing_info 截断前后计数` |
| `EvidenceAvailability` | `NONE / PRESENT / TRUNCATED` |
| `SourceResolutionStatus` | `RESOLVED / UNRESOLVED / AMBIGUOUS` |

领域异常（`evidence/errors.py`）：
- `KnowledgeSearchError`（基类）
- `KnowledgeSearchNotReadyError`（未 init 即查）
- `KnowledgeSearchExecutionError`（Kernel 执行失败 / `status="failure"`）
- `InvalidKnowledgeQueryError`（空 / 纯空白 query）

## 4. KnowledgeSearchPort（`protocols/knowledge_search.py`）

```python
@runtime_checkable
class KnowledgeSearchPort(Protocol):
    async def search(self, query: str) -> KnowledgeSearchResult: ...
```

- Tool 依赖这个端口而非具体 Adapter → **依赖倒置**。
- `@runtime_checkable` 允许 fake 与 adapter 以结构/动态方式满足协议。
- 单元测试用 `FakeKnowledgeSearchPort` 证明 Tool 完全不依赖 LightRAG。

## 5. RagSearchTool（`tools/rag_search.py`）

- Agent-facing 输入刻意最小：只有 `query`（`RagSearchInput`，拒绝空/纯空白）。
- 输出 `RagSearchResult`：`status ∈ {SUCCESS, NO_EVIDENCE, ERROR}` + `evidence + citations + diagnostics + error`。
- **关键语义**：`RagSearchTool` 是**知识检索工具**，不是最终作答工具。它返回结构化证据/引用/诊断，
  由未来的 Agent 层推理与合成答案。
- 关闭代码路径上无 LightRAG 类型泄漏；任何 `Exception` 都会被归一化进 `ERROR`，绝不让未知异常冲上 Agent 层。
- `EvidenceAvailability.NONE → STATUS.NO_EVIDENCE`，绝不把"空证据"默默透传成"没有答案"。

## 6. LightRAGAdapter（`adapters/lightrag/adapter.py`）

唯一允许 import LightRAG 的生产模块。职责：

1. 生命周期：`initialize()`（幂等）→ `search()` → `close()`（幂等，可在 `finally` 使用）。
   `initialize()` 内 `finalize_storages()` 保证资源释放。
2. 构建 `QueryParam`（mode / top_k / rerank / include_references）——**不向上暴露**。
3. 只调用 `aquery_data`（不再复跑 `aquery`）。
4. 校验原始响应：`status != "success"` → `KnowledgeSearchExecutionError`（含 `failure_reason`）。
5. 交给 `map_query_data_to_result()` 转领域模型。
6. 异常归一化：`TypeError(NoneType)`、`EmptyQueryError`、`ValueError(Unknown mode)` 等
   一律压成 `KnowledgeSearch*Error` 领域异常。

### workspace 隔离（本阶段新增）

LightRAG 的 `doc_status` 去重与存储按 `workspace` 命名空间划分；`workspace` 为空时共享全局。
因此 `build_lightrag` / `AdapterSettings` 增加了 `workspace` 字段：
- 生产上可为不同的知识库 / 隔离环境设置独立 workspace，避免跨库去重与 store 串扰。
- 集成测试用 `tmp_path` 派生的唯一 workspace，解决"同一会话跑 Stage 1 + Stage 2 时
  Stage 2 对新 tmpdir 仍判重复、且新 store 为空导致查不到证据"的问题。

## 7. SourceResolver（`adapters/lightrag/source_resolver.py`）

Kernel 把 citation 的 `file_path` 归一化为 **basename**。Resolver 扫描允许的 knowledge roots，
返回三态结果：

| 状态 | 含义 | 处理 |
|---|---|---|
| `RESOLVED` | 恰好一个匹配 | `source_path` 填写完整路径 |
| `UNRESOLVED` | 无匹配 | `source_path=None`，保留 `source_name` |
| `AMBIGUOUS` | 同名多于一个 | `source_path=None`，绝不静默选择 |

## 8. Result Mapper（`adapters/lightrag/mapper.py`）

纯函数 `map_query_data_to_result(data, query, resolver) -> KnowledgeSearchResult`：
- chunk / entity / relationship / reference → 领域模型；
- references 驱动 citations，并把唯一的引用路径回填到 chunk / entity；
- `metadata.processing_info` → `diagnostics` 与 `EvidenceAvailability`（**只会在内核明确报告截断时**返回 `TRUNCATED`，绝不声称 SUFFICIENT）。
- 可离线用 fixture 测（`tests/unit/test_lightrag_result_mapper.py`）。

## 9. 组合根（`bootstrap.py`）

`create_lightrag_adapter(settings, ...)` + `build_rag_search_tool(adapter=...)`。
应用层唯一知道具体 Adapter 的地方；不直接 import LightRAG；不创建 Agent（Stage 4）。

## 10. 关键工程事实（踩过的坑）

- **duplicate document detection 是全局的**：LightRAG 的 `doc_status` 去重按 `workspace` 划分，
  与 `working_dir` 解耦。用全新 tmpdir 仍会命中"全局已有同名文件" → 用唯一 `workspace` 隔离。
- **fresh working_dir + 空 store = 查不到证据**：即使去重没拦住，新 kernel 的 vdb/graph 为空，
  query 返回 `status="failure"`(`no_results`)。因此集成测试必须：唯一 workspace + 真正 ingest。
- **不能只靠 `working_dir` 隔离**：`workspace`（字段，默认来自全局 `WORKSPACE` env）才是去重键。
- **`from __future__ import annotations` 影响签名检查**：架构测试用 `typing.get_type_hints` 解析，而非直接读 `signature`。

## 11. 测试矩阵

| 测试 | 用途 | 依赖 |
|---|---|---|
| `tests/architecture/test_boundaries.py` | 强制依赖边界（tools→adapters 禁止等） | 离线 |
| `tests/unit/test_knowledge_search_contract.py` | Port 协议合规 + 签名不含 vendor 类型 | 离线 |
| `tests/unit/test_source_resolver.py` | basename 解析三态 | 离线 |
| `tests/unit/test_lightrag_result_mapper.py` | raw dict → 模型（fixture 驱动） | 离线 |
| `tests/unit/test_lightrag_adapter.py` | 生命周期 / 异常归一化（fake kernel） | 离线 |
| `tests/unit/test_rag_search_tool.py` | Tool 只依赖 Port（fake port） | 离线 |
| `tests/integration/test_rag_search_tool_e2e.py` | 真实 Kernel E2E（唯一 workspace） | 需要 `DEEPSEEK_API_KEY` + Ollama，无凭据自动 skip |

全部：**50 passed**（pytest）+ ruff check/format + mypy 全绿。

## 12. Non-goals（本阶段不做）

- 不实现 `Query Router` / `RetrievalPlan` / `RetrievalStrategy`（Stage 3）。
- 不引入 Agent / Tool Registry / Tool Calling Loop（Stage 4）。
- 不实现 hallucination guard（属于 Tool/Agent 层语义，本阶段仅用 `NO_EVIDENCE` 显式表达"证据不足"）。

---
更新时机：本报告随 pinned commit 与真实运行结果更新；若 kernel 升级导致 `aquery_data`
结构或去重语义变化，需重跑 baseline 与集成测试并更新本文件。