# LightRAG Source Integration

本文档记录 Stage 0 的 LightRAG source 接入事实与 source probe 结果。
**所有内容来自 pinned source checkout，不是来自假设或 PyPI 文档。**

## 1. 官方仓库与接入方式

| 项 | 值 |
|---|---|
| Official repo | `https://github.com/HKUDS/LightRAG.git` |
| Submodule path | `third_party/LightRAG` |
| Remote URL (fetch) | `https://github.com/HKUDS/LightRAG.git` |
| Remote URL (push) | `https://github.com/HKUDS/LightRAG.git` |
| **Pinned commit SHA** | `02dcd8df754ec312b807bdd4d67737b97bc38679` |
| Branch / detached | `main`（branch 状态，非 detached HEAD） |
| Working tree status | clean |
| LICENSE | 存在（MIT） |
| README | 存在（`README.md`） |

### 记录命令（原始输出存档依据）

```bash
git -C third_party/LightRAG remote -v
git -C third_party/LightRAG rev-parse HEAD
git -C third_party/LightRAG status --short
git -C third_party/LightRAG branch --show-current
```

## 2. 安装方式

```bash
git submodule add https://github.com/HKUDS/LightRAG.git third_party/LightRAG
python -m venv .venv
python -m pip install -e third_party/LightRAG   # 必须是 source editable，而不是 PyPI wheel
python -m pip install -e ".[dev]"
```

> 本机网络注意：开发机通过 TUN 模式梯子访问 GitHub。Git 使用 Windows schannel
> 后端可正常连接（`git config http.sslBackend schannel`，仅写入本地 repo config，
> 不随仓库提交）。pip 走清华镜像 `https://pypi.tuna.tsinghua.edu.cn`。

## 3. Python 环境

| 项 | 值 |
|---|---|
| Python version | 3.12.9 |
| Python executable | `C:\Users\23304\AppData\Local\Programs\Python\Python312\python.exe` |
| Virtualenv | `.venv/`（项目根目录） |

## 4. Import Verification

```bash
python -c "from lightrag import LightRAG; from lightrag import QueryParam; import lightrag, pathlib; p=pathlib.Path(lightrag.__file__).resolve(); print(p)"
# → D:\myself-prove\Polaris Agentic RAG\third_party\LightRAG\lightrag\__init__.py
```

Window path 验收（正反斜杠适配）：

```bash
python -c "import lightrag, pathlib, os; p=pathlib.Path(lightrag.__file__).resolve(); normv=os.path.normpath(str(p)); assert 'third_party'+os.sep+'LightRAG' in normv or 'third_party/LightRAG' in normv, normv"
# → 通过
```

**source path 验收结果：`lightrag.__file__` 解析到 `third_party/LightRAG`。** 未使用 PYTHONPATH 伪造。

包元数据：`lightrag-hku == 1.5.8`（editable source install）。

## 5. Source Probe（21 项必查结果）

probe 实现在 `src/polaris_agentic_rag/adapters/lightrag/source_probe.py`。
以下均来自 pinned commit `02dcd8df`：

| Capability | Source Location | Current Finding | Future Integration |
|---|---|---|---|
| `LightRAG` 定义 | `lightrag/lightrag.py` (`class LightRAG`，line 684) | exists | LightRAGAdapter 构造目标 |
| `LightRAG` export | `lightrag/__init__.py` `__all__` + lazy `__getattr__` | exists | — |
| `QueryParam` 定义 | `lightrag/base.py` (`class QueryParam`，line 90) | exists | Adapter 内部映射 |
| `QueryParam` export | `lightrag/__init__.py` lazy export | exists | — |
| `insert` | `LightRAG.insert`（`_run_sync` wrapper） | exists | ingest baseline |
| `ainsert` | `LightRAG.ainsert`（`lightrag.py` line 2310） | exists | ingest baseline |
| `query` | `LightRAG.query`（line 4819，`_run_sync` wrapper） | exists | sync query 兼容 |
| `aquery` | `LightRAG.aquery`（line 4843，wrapper → `aquery_llm`） | exists | 主查询路径 |
| `query_data` | `LightRAG.query_data`（line 4876） | exists | sync 结构化检索 |
| `aquery_data` | `LightRAG.aquery_data`（line 4901） | exists | Evidence / structured data 映射 |
| Query Modes | `QueryParam.mode = Literal[...]`（base.py line 93） | `local` / `global` / `hybrid` / `naive` / `mix` / `bypass` | Retrieval Strategy 输入 |
| `only_need_context` | `QueryParam`（base.py line 102） | exists | 上下文直取 |
| `only_need_prompt` | `QueryParam`（base.py line 105） | exists | prompt 直取 |
| `include_references` | `QueryParam`（base.py line 171） | exists（默认 False） | citation |
| `enable_rerank` | `QueryParam`（base.py line 166） | exists（默认 env `RERANK_BY_DEFAULT`=true） | rerank 开关 |
| `top_k` | `QueryParam`（base.py line 114） | exists | strategy 参数 |
| `chunk_top_k` | `QueryParam`（base.py line 117） | exists | strategy 参数 |
| LLM function 注入 | `LightRAG.llm_model_func`（lightrag.py line 995）+ `llm_model_name` / `llm_model_kwargs` | exists; 必填（`llm_model_func must be provided`，line 1909） | LLM provider |
| Role-specific LLM config | `lightrag/llm_roles.py`：`ROLES = (extract, keyword, query, vlm)` + `RoleLLMConfig` | exists（keyword extraction LLM 等按 role 注入） | 角色化模型配置 |
| Embedding function 注入 | `LightRAG.embedding_func: EmbeddingFunc | None`（line 933） | exists | Embedding provider |
| Rerank function 注入 | `LightRAG.rerank_model_func`（line 1057）+ `rerank_model_max_async` | exists | Rerank provider |
| Storage 配置 | dataclass 字段 `kv_storage` / `vector_storage` / `graph_storage` / `doc_status_storage`（默认 `JsonKVStorage` / `NanoVectorDBStorage` / `NetworkXStorage` / `JsonDocStatusStorage`）+ `vector_db_storage_cls_kwargs` | exists | storage strategy |
| `initialize_storages` | `LightRAG.initialize_storages`（line 1986） | exists; 官方强调构造后**必须**调用 | 生命周期 |
| `finalize_storages` | `LightRAG.finalize_storages`（line 2163） | exists | 生命周期 |
| references / citation 数据 | `aquery_data` data.references `[{reference_id, file_path}]`；chunks 带 `reference_id`；`aintext(..., file_paths=...)` 提供来源 | exists | citation contract |
| structured retrieval data | `aquery_data` → `{"status", "message", "data": {entities, relationships, chunks, references}, "metadata": {query_mode, keywords, processing_info}}` | exists | Evidence mapping |
| SDK 查询失败行为 | 查询空串等 → raise（`query_validation` / exceptions）；**`aquery_data` 查询级失败返回 `{"status": "failure", "message": ..., "data": {}}`**；LLM/存储失败 raise 异常（`lightrag/exceptions.py`：`APIStatusError` 族、`StorageNotInitializedError`、`PipelineBackpressureError` → HTTP 429 等） | exists | failure model |
| API Server 失败形式 | REST 错误：HTTP 状态码 + 错误 body（`ConflictError`→409、`PipeBackpressure`→429、存储控制面→503 等）；鉴权 `AUTH_ACCOUNTS` / `LIGHTRAG_API_KEY` | exists | — |
| Core SDK vs API Server 差异 | Core：进程内对象 + `async def` 直接调用，异常面向调用方；Server：`lightrag/api/lightrag_server.py` FastAPI + Ollama 兼容 API，额外提供 `/documents/*` 文件级管理、鉴权、并发/背压 | documented | 生产部署候选 |

### 附加必查项说明

- **LLM role 存在**：`ROLES = ("extract", "keyword", "query", "vlm")`，支持 general LLM、keyword extraction LLM、summary/query 等按 role 独立配置。
- **关键字注入位置**：实体/关系抽取、关键词抽取、query 三大阶段的 LLM 调用均经由 role wrapper（`_RoleLLMMixin`）。
- **`aquery_llm`**：`aquery` 现在的实现入口，返回完整结果（`llm_response`、retrieval 数据等），`aquery` 仅向后兼容地取 `llm_response.content`。
- **`bypass` mode**：所有数据数组为空，用于直接 LLM 查询（绕过检索）。

## 6. 为什么当前不修改 LightRAG（No Patch）

- Stage 0 禁止修改 `third_party/LightRAG` 任何源码。
- 若未来需要 patch，必须先创建新 ADR，说明：什么问题、为什么 Adapter 无法解决、为什么需要 patch、是否 fork、submodule 策略、upstream contribution 策略。
- 当前 probe 未发现需要 patch 的阻断性问题；已有差异以「记录」方式处理（如 default query mode 现在是 `mix` 而非 `hybrid`）。

## 7. Core SDK vs REST API（客观记录）

官方 LightRAG 仓库同时提供 Python Core SDK 与 FastAPI Server（`lightrag-server` / `uvicorn lightrag.api.lightrag_server:app`），并有较完整的 Server 文档（`docs/LightRAG-API-Server.md`）。官方文档面向普通应用也覆盖 Server 集成方式（env 配置、鉴权、文件管理端点）。

本项目当前主路径明确选择 **Python Core + Source Editable Install**，理由：
- source-level learning / inspection / debugging / interface exploration；
- 直接观察 retrieval metadata 与 `aquery_data` 结构化返回；
- 便于 Adapter 设计与 Agentic RAG Evaluation；
- 面试演示价值。

**不宣称 Source Core 一定比 REST 更适合生产。** 未来生产部署可能重新评估 REST Server。

## 8. 风险与已知差异

- default `QueryParam.mode` 在 pinned 版本为 `"mix"`（旧文档常见 `hybrid`）。
- `include_references` 默认 `False`，Adapter 未来需显式开启。
- `enable_rerank` 默认受 `RERANK_BY_DEFAULT` 环境变量影响（默认 `true`），但未配置 rerank model 时会告警。
- lightrag 包元数据名称为 `lightrag-hku`，版本 `1.5.8`。
- Windows 开发机访问 GitHub 需代理/TUN；git 使用 schannel 后端（本地配置，非提交内容）。

## 9. Stage 1 Objectives（本文件更新时机）

Stage 0 只做静态 probe。Stage 1 将基于 pinned source 验证：

- 真实受控 LLM provider 与 Embedding provider 注入
- storage lifecycle（initialize/finalize）
- ingest example knowledge base
- `aquery` / `aquery_data` 在真实数据上的输出
- query mode 对比（含 `mix` 与 rerank）
- references 与 `aquery_data` 结构化数据落盘观察
- unknown-question / insufficient-evidence 行为
- baseline evaluation cases

届时如 probe 结论与此文档不一致，以 pinned source 为准并更新此表。