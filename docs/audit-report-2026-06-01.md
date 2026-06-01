# CodeGraph Explorer 后端功能审计报告

**日期：** 2026-06-01
**范围：** 全后端（CLI / MCP / 索引 / 存储 / 图查询 / Context Pack / Search / Configure / Doctor / Watch / 测试）

---

## 总体评估

项目核心功能完备，MCP 工具集已实现 MCP-first 定位。代码质量整体良好，有清晰的分层职责和丰富的测试覆盖。主要问题集中在：MCP 响应信封非标准、SQLite 无 FTS5 全文搜索、部分边界 case 的健壮性不足。

---

## 1. CLI 命令

### 已完成且可用

| 命令 | 用途 | 状态 |
|------|------|------|
| `init` / `index` (hidden) | 全量索引项目 | ✅ 可用 |
| `update` | 重新 pip install -e 更新自身 | ✅ 可用（仅 editable 安装） |
| `status` | 检查索引新鲜度（changed/added/deleted） | ✅ 可用 |
| `search` | 按关键词搜索符号 | ✅ 可用 |
| `explain` | 查看符号详情及调用关系 | ✅ 可用 |
| `impact` | 影响面分析（risk level + affected files） | ✅ 可用 |
| `context` | 生成 Evidence Pack（summary/full/markdown） | ✅ 可用 |
| `api` | 启动 FastAPI HTTP API（uvicorn 子进程） | ✅ 可用 |
| `watch` | 启动文件监听 + 自动增量索引 | ✅ 可用 |
| `mcp` (debug) | 直接启动 MCP stdio server（跳过校验） | ✅ 可用 |
| `serve --mcp` | 标准化 MCP server 启动入口 | ✅ 可用 |
| `serve --mcp --check` | 校验环境后退出 | ✅ 可用 |
| `doctor` | 10 项全面诊断检查 | ✅ 可用 |
| `configure all/claude/cursor/show/remove` | MCP 配置文件管理 | ✅ 可用 |

### 已完成但需加固

| 问题 | 严重度 | 详情 |
|------|--------|------|
| `explain --depth` 被静默忽略 | 低 | depth 参数 parse 后未传给 `get_callers`/`get_callees` |
| `doctor` 对 `index.sqlite` 的强制要求 | 中 | 若 `--no-sqlite` 使用过，doctor 误报 "Missing index files: index.sqlite" |
| `init` 中 SQLite 错误静默吞掉 | 低 | `except Exception: pass` 不记录失败原因 |
| `api` 命令：缺失 index 仅 warning 不退出 | 中 | 继续启动 uvicorn 大概率后续崩溃 |
| `update` 仅支持 editable 安装 | 低 | 非 editable 安装时提示 "re-clone"，过于激烈 |
| `_find_node` 符号模糊匹配非确定性 | 低 | 多候选时返回遍历顺序第一个，非稳定排序 |

---

## 2. MCP Server

### 已完成且可用

- **9 个 MCP 工具**：`search_symbols`、`get_symbol`、`get_callers`、`get_callees`、`get_neighbors`、`get_impact`、`build_context_pack`、`repo_status`、`repo_summary`
- **两种响应模式**：`compact`（精简字段）和 `standard`（完整字段）
- **结构化错误码**：`INDEX_MISSING`、`SYMBOL_NOT_FOUND`、`AMBIGUOUS_SYMBOL`、`INVALID_ARGUMENT`
- **符号解析**：支持精确 ID 匹配 + 模糊（名称/路径）匹配，带 `expected_type` / `path_hint` 消歧
- **过时警告**：每个响应都包含 `warnings` 数组，检测 index stale
- **项目根检测**：CLI arg → 环境变量 `CODEGRAPH_PROJECT_ROOT` → CWD 向上遍历
- **自动启动**：通过 `codegraph serve --mcp` 作为 MCP stdio 子进程运行，由 MCP 客户端管理生命周期
- **Watch 集成**：支持 `--watch` / `CODEGRAPH_WATCH=1` 启用文件监听 + 自动重载 store

### 已完成但需加固

| 问题 | 严重度 | 详情 |
|------|--------|------|
| **响应信封非标准 MCP 协议** | **高** | 所有工具通过 `_respond_ok`/`_respond_error` 包装为自定义 JSON 信封（`{ok, tool, data, error, warnings, index_status, meta}`）然后返回 JSON 字符串。FastMCP 本应直接返回 Python 数据结构。双重 JSON 封装导致通用 MCP 客户端无法内省响应结构。虽然当前 Claude Code 可用（因为 FastMCP 将 str 传入 `content[0].text`），但与 MCP 规范不一致 |
| **无 catch-up sync** | 中 | 检测到 stale 时仅在响应中附 warning，不自动触发增量索引。完全依赖客户端处理 |
| **`search_symbols` hardcode limit=9999** | 低 | 先从 store 拉取全部结果再在 MCP 层分页，大仓库内存效率差 |
| **每次工具调用都做磁盘 I/O** | 低 | `_collect_warnings()` 每次都读 state.json + metadata.json + 检查文件存在性，影响延迟 |
| **`_load_store` 异常捕获过宽** | 中 | `RuntimeError` 捕获可能把损坏的 graph.json 当作 INDEX_MISSING 返回，信息不准确 |
| **`_reload_store` 静默失败** | 中 | watch 回调中的 store 重载失败被 `except Exception: pass` 吞掉，用户无感知 |
| **`ensure_ascii=False + indent=2`** | 低 | 非标准 JSON 输出格式，payload 偏大 |

---

## 3. 索引系统

### 已完成且可用

- **语言支持**：Python 3.8+（AST-only，无 tree-sitter）
- **符号提取**：
  - `file`、`module`、`class_`、`function`、`method`、`test`、`import_`、`external_symbol`
  - 函数签名重建（含类型注解、`*args`/`**kwargs`、返回类型）
  - 类继承检测 + Pydantic/dataclass/Enum 自动标记
  - FastAPI/Flask 路由装饰器检测
  - 路径/文件名启发式标记（models/、store/、config.py → model/store/config tag）
- **调用提取**：
  - 21 种 resolution 策略，每种带 confidence + reason + evidence
  - 6 种 import 调用模式（exact/alias/relative/chained）
  - self 方法、self.attr 实例、构造函数链、参数类型提示、实例变量追踪
- **Import 解析**：项目内部 vs stdlib vs 外部启发式分类
- **外部边后处理**：`_resolve_external_edges` 通过 qualified_name 重写 external→本地节点
- **测试关系发现**：直接调用（0.90）+ 名称启发式（0.65）+ 文件名匹配（0.55）
- **增量索引**：文件级删除+重建，handle changed/added/deleted
- **索引锁**：PID + 超时（300s）陈旧检测，原子写入（tmp + os.replace）
- **Watch**：watchdog（优先）→ polling 回退，500ms 去抖，pending 队列防丢失

### 已完成但需加固

| 问题 | 严重度 | 详情 |
|------|--------|------|
| **无 tree-sitter / 仅 Python** | 中 | 纯 `ast` 模块，无法解析语法错误的文件。不支持其他语言 |
| **嵌套函数不提取** | 低 | 嵌套 `def`/`async def` 被静默忽略 |
| **无变量/常量提取** | 低 | `CONSTANT = 42` 等顶层赋值不产生符号节点 |
| **PascalCase 构造函数跳过** | 中 | `call_extractor.py:609` 将大写开头的函数调用当作类构造器跳过，`JSONParser()` 等工厂函数调用被丢弃 |
| **无动态/间接调用** | 中 | `getattr()`/`__call__`/`functools.partial`/decorator 包装不被追踪 |
| **增量保存时全量重新指纹扫描** | 低 | `_save_index_artifacts` 每次都 `scan_python_files`（全量 SHA256），大仓库慢 |
| **无并行索引** | 低 | 文件顺序处理，无 multiprocessing |
| **无 `__all__` 解析** | 低 | 不利用 `__all__` 限定导出范围 |
| **装饰器不产生调用边** | 中 | `@decorator(args)` 在 `visit_FunctionDef` 中被忽略 |

---

## 4. 存储系统

### 已完成且可用

- **FileStore（JSON）**：`nodes.json` + `edges.json` + `metadata.json`（Pydantic 序列化）
- **SqliteStore**：`index.sqlite`（nodes + edges 表，B-tree 索引）
- **IndexStateStore**：`state.json`（原子写入 via `os.replace`）
- **增量删除**：`delete_nodes_by_file` + `delete_edges_by_file`
- **批量写入**：自动分块（500 行为一批）
- **Schema version**：`"1.0.0"` 记录在 `metadata.json` 和 `CodeGraph.schema_version`

### 已完成但需加固

| 问题 | 严重度 | 详情 |
|------|--------|------|
| **无 FTS5 全文搜索** | **高** | 所有文本搜索使用 SQL `LIKE` 子串匹配。大仓库搜索性能差。`sqlite_utils.py` 中无 `CREATE VIRTUAL TABLE` 语句 |
| **JSON 写入无原子性** | 中 | `FileStore.save_nodes/edges` 用 `write_text` 直接覆盖，中途崩溃会损坏文件。`state_store` 用 `os.replace` 是好的实践 |
| **SQLite → Pydantic 键名不匹配** | 中 | SQLite 列 `edge_metadata` vs `GraphEdge.metadata`，`_row_to_edge` 返回 `edge_metadata` 键而非 `metadata`，导致 `GraphEdge(**data)` 失败 |
| **JSON + SQLite + State 三副本无一致性保证** | 中 | 若索引在写 JSON 后 SQLite 前崩溃，三存储状态不一致，且无法自动检测 |
| **无 schema 版本迁移** | 低 | `schema_version` 字段存在但从未被读取/校验/迁移 |
| **`GraphEdge.id` 默认 `""`** | 低 | 空 ID 在 SQLite `INSERT OR REPLACE` 下可能导致意外的覆盖 |
| **SQLite 无 WAL 模式** | 低 | 默认 journal_mode，并发读取性能未优化 |

---

## 5. Impact / Context Pack

### 已完成且可用

- **`get_impact`**：
  - confirmed_impact（confidence >= 0.6）和 possible_impact（低置信度）分离
  - upstream_callers + downstream_callees 传递遍历（depth 可配，默认 2）
  - 类级别聚合（类无直接调用者时聚合方法）
  - 模型/配置/存储依赖检测（via imports 边）
  - 外部/未解析分离
  - 测试发现（tested_by + 测试调用者）
  - 风险评估：low / medium / high / critical（基于敏感路径 / 公开 API / 状态变更 / 调用者数量）
  - 两种 impact_mode：conservative（直接） / balanced（depth=2 + models/config）

- **`build_context_pack`**：
  - 三种输出模式：summary（精简 JSON）/ full（完整 JSON）/ markdown（导出文件）
  - 任务意图分类：9 种策略（write_tests, fix_bug, refactor, analyze_impact, …）
  - 入口点发现：符号引用提取 + 关键词搜索 + 回退
  - Token budget 管理：4 chars/token 估算，优先级降级级联，关键/高优先级永不被丢弃
  - **无 reading_plan** ✅（`reading_plan.py` 文件不存在，`ContextPack` schema 无此字段，测试有断言）
  - **无 agent_instructions** ✅（代码库 0 引用，测试有断言）
  - **无 recommended_context** ✅（同上）

### 已完成但需加固

| 问题 | 严重度 | 详情 |
|------|--------|------|
| **敏感路径检测过于宽泛** | 低 | `_is_sensitive_path` 用 `in` 子串匹配，`authorization.py` 匹配 `"auth"`（应只匹配 `auth` 目录/文件） |
| **风险评估原因代码为自由文本** | 低 | `reasons` 是字符串列表而非枚举，机器不可过滤 |
| **context_pack 中调用图遍历仅 depth=1** | 中 | `build_context_pack` 的调用图收集是单跳的（仅入口点的直接边），`depth` 参数仅用于 impact 分析。与参数名不一致 |
| **`_find_model_config_store_deps` 无独立单元测试** | 低 | 仅通过集成测试覆盖 |
| **类级别聚合无深度限制** | 低 | 类有 100 个方法时全部聚合，忽略 depth 参数 |
| **Markdown 导出返回绝对文件系统路径** | 低 | `markdown_path` 在远程 MCP 场景下可能不可达 |

---

## 6. Search

### 已完成且可用

- **多字段搜索**：ID、name、file_path、qualified_name、docstring
- **评分算法**：ID 精确匹配=1.0，名称精确=1.0，名称片段=0.8，qualified_name=0.9，路径=0.7，docstring=0.5
- **match_sources 累积**：同一符号可在多个字段匹配，记录所有来源
- **过滤**：type_filter、file_filter、exclude_tests
- **排序/分页**：按分数降序，limit/offset 分页
- **fuzzy 匹配**：`str.lower() in str.lower()` 子串匹配

### 已完成但需加固

| 问题 | 严重度 | 详情 |
|------|--------|------|
| **无 FTS5** | **高** | 同存储层 — 依赖 Python 内存中 `str.contains` 做 O(n) 全扫描 |
| **无加权融合评分** | 低 | 多字段匹配时取 max 而非加权和，`match_sources` 列表不可排序 |
| **大小写均转小写** | 低 | 无法区分大小写敏感匹配的权重 |
| **旧版参数兼容** | 低 | `type_filter`/`file_filter`/`max_results` 作为 `types`/`paths`/`limit` 的别名存在，API 略显冗余 |

---

## 7. Configure / Doctor

### 已完成且可用

- **configure all/claude/cursor**：自动写入 MCP 配置到 `~/.claude.json` / `~/.cursor/mcp.json` / project-level `.mcp.json`
- **幂等**：默认不覆盖已有配置，`--force` 强制覆盖
- **Python 绝对路径**：默认使用 `sys.executable`（Windows 可靠）
- **configure show**：展示每个 target 的配置状态
- **configure remove**：删除 `"codegraph"` key，返回 `"removed"` / `"not_configured"`
- **doctor**：10 项检查（CLI 可用性、Python 版本、包路径、项目根、索引状态、MCP 配置、项目根校验、serve 就绪、MCP 命令存在性、MCP 启动测试）

### 已完成但需加固

| 问题 | 严重度 | 详情 |
|------|--------|------|
| **doctor 强制要求 index.sqlite** | 中 | 同 CLI — 如果 `--no-sqlite` 使用过，doctor 报误报 |
| **configure 不校验 root 路径存在性** | 低 | `Path(root).resolve()` 不检查目录是否真实存在 |
| **无 Cursor 特定格式验证** | 低 | 写入与 Claude Code 相同的 JSON 结构，Cursor 可能有不同的 schema 期望 |
| **doctor 中 MCP 启动检查超时 30s** | 低 | 对慢速机器可能不够 |

---

## 8. Watch / Auto-sync

### 已完成且可用

- **Watchdog（优先）+ Polling（回退）**：自动检测 `watchdog` 可用性
- **事件类型**：modified / created / deleted / moved
- **去抖**：500ms debounce（可配），累积变更集合
- **Pending 队列**：同步进行中如有新变更，同步完成后立即重新运行
- **增量索引**：变更触发 `run_incremental_index`
- **状态管理**：通过 `IndexStateStore` 跟踪 indexing / ready / error 状态
- **忽略目录**：`.git`, `.venv`, `__pycache__`, `.codegraph` 等
- **独立入口**：`codegraph watch ROOT`（阻塞式前台循环）
- **MCP 集成**：`serve --mcp --watch` 或 `CODEGRAPH_WATCH=1`

### 已完成但需加固

| 问题 | 严重度 | 详情 |
|------|--------|------|
| **默认不启用 watch** | 中 | `serve --mcp` 不带 `--watch`，需手动加环境变量。推荐配置中不含 watch |
| **轮询回退开销** | 低 | `WATCH_GLOBS` 每种 pattern 做一次 `root.glob()`，大仓库多 pattern 时 I/O 开销大 |
| **目录重命名不处理** | 低 | `on_moved` 检测到 `is_directory` 后 return，文件可能静默不同步 |
| **去抖期间的竞态** | 低 | 文件变更+删除在去抖窗口内只留下 deleted 事件，changed 丢失（但这是合意的） |
| **watchdog 为可选依赖** | 低 | 未安装时静默降级为 polling，用户可能不知情 |

---

## 9. 已废弃 / 前端

### 已清理

- **reading_plan** ✅ — `reading_plan.py` 文件不存在，`ContextPack` schema 无此字段，代码库 0 引用
- **agent_instructions** ✅ — 同上
- **recommended_context** ✅ — 同上
- **Dashboard 前端代码** ✅ — 无 `frontend/` 目录，无 React/ReactFlow/GraphCanvas 代码
- **API 中的 Dashboard 路由** ✅ — `backend/codegraph/api/` 中 0 引用

### 清理残留

| 残留 | 详情 |
|------|------|
| `.gitignore` 中 `frontend/tsconfig.tsbuildinfo` 和 `frontend/.vite/` | 无实际影响，可保留或清理 |
| PRD 文档中大量 Dashboard 引用 | 历史规划文档，保留合理 |
| `docs/PRD/07-api-and-dashboard.md` | 同上 |

---

## 10. 测试 / Benchmark

### 测试覆盖总览

| 子系统 | 测试文件 | 覆盖程度 |
|--------|----------|----------|
| Graph Models + Store | `test_graph_models.py` | 全面 |
| Graph Edge API | `test_graph_edge.py` | 良好 |
| Graph Query | `test_graph_query.py` | 良好 |
| Graph Impact | `test_graph_impact.py` | 非常全面 |
| Indexer | `test_indexer.py`（3394 行） | 非常全面（扫描/解析/符号/调用/图构建/路由/测试发现/中文路径） |
| Context Pack | `test_context_pack.py` | 全面（含无 reading_plan 断言） |
| Context Strategies | `test_strategies.py` | 非常全面（9 种意图类型 + 组合策略） |
| Context Selection | `test_selection.py` | 非常全面 |
| Token Budget | `test_token_budget.py` | 良好 |
| MCP Tools | `test_mcp_tools.py`（1491 行） | 非常全面（信封/搜索/获取/调用者/被调用者/邻居/影响/状态/摘要/错误码/分页/模糊解析/源码控制/无操作建议） |
| CLI | `test_cli.py` | 良好 |
| Configure | `test_configure.py` | 非常全面 |
| Serve/Doctor | `test_serve_doctor.py` | 非常全面 |
| Watch | `test_watch.py` | 全面（锁/状态/观察模式/增量/轮询回退） |
| Storage | `test_storage.py` | 全面 |
| Engineering Hardening | `test_engineering_hardening.py` | 全面（中文路径/符号链接安全/SQLite 分块/过时检测/保守影响/统一警告） |
| Agent Benchmark | `tests/agent_benchmark/` | 良好（3 个 fixture 项目，4 种任务类别，recall/token/file-read/grep 指标） |

### 测试覆盖缺口

- **MCP 线路协议测试**：无真正的 MCP stdio JSON-RPC 端到端测试
- **`_find_model_config_store_deps` 独立单元测试**：仅通过集成测试覆盖
- **压力测试**：无大型代码库（10k+ 文件）性能测试
- **并发测试**：无多线程索引/查询并发安全测试
- **SQLite → Pydantic 键名不匹配**：该 bug 未被测试捕获（`edge_metadata` vs `metadata`）

### Benchmark 质量门控

| 指标 | 阈值 | 当前 |
|------|------|------|
| Recall >= baseline | ≥ 8/12 | 11/12 |
| Token reduction | ≥ 20% | ~29% |
| Files read reduction | ≥ 25% | ~78% |
| grep/read reduction | ≥ 30% | ~90% |

---

## 当前后端主路径

```
用户执行 codegraph init → scanner.py 扫描 .py 文件
  → parser_python.py AST 解析
  → symbol_extractor.py 提取符号节点
  → call_extractor.py 提取调用边（21 种 resolution）
  → graph_builder.py 构建结构边 + 外部边解析 + 测试关系
  → FileStore 写 nodes.json / edges.json / metadata.json
  → SqliteStore 写 index.sqlite（best-effort）

MCP Agent 连接 → codegraph serve --mcp 启动 mcp_server.py（FastMCP stdio）
  → _load_store() 从 JSON 加载到 GraphStore（内存）
  → 9 个 @mcp.tool() 处理查询
  → 每个响应附 _collect_warnings() 检查 stale

开发者验证 → codegraph doctor（10 项检查）
  → codegraph status（新鲜度检查）
  → codegraph configure all（写 MCP 配置）
```

---

## 附录：关键文件路径

```
backend/codegraph/
├── __main__.py                  # python -m codegraph 入口
├── __init__.py                  # __version__ = "0.1.0"
├── mcp_server.py                # MCP server（9 tools, 2845 行）
├── configure.py                 # MCP 配置管理
├── cli/main.py                  # 所有 CLI 命令（Typer）
├── indexer/
│   ├── scanner.py               # 文件扫描 + SHA256 指纹
│   ├── parser_python.py         # Python AST 解析
│   ├── symbol_extractor.py      # 符号提取 + 路由检测
│   ├── call_extractor.py        # 调用提取（21 resolution）
│   ├── graph_builder.py         # 图构建 + 外部边解析
│   ├── incremental.py           # 增量索引
│   ├── lock.py                  # IndexLock（PID + 超时）
│   ├── watch.py                 # WatchSyncManager
│   └── status.py                # detect_status / StatusResult
├── graph/
│   ├── models.py                # Node/Edge/CodeGraph Pydantic models
│   ├── store.py                 # GraphStore（内存）
│   ├── query.py                 # search/callers/callees/subgraph
│   ├── impact.py                # analyze_impact（传递遍历）
│   ├── confidence.py            # 29 resolution → confidence 映射
│   └── warnings.py              # 10 warning types
├── context/
│   ├── models.py                # ContextPack schema
│   ├── pack_builder.py          # build_context_pack 主流程
│   ├── selection.py             # ContextSelector（token budget）
│   ├── ranking.py               # 入口点排序
│   ├── strategies.py            # 9 task strategies
│   ├── token_budget.py          # TokenBudget 估算
│   └── markdown_exporter.py     # Markdown 导出
├── storage/
│   ├── file_store.py            # JSON 读写
│   ├── sqlite_store.py          # SQLite 存储
│   ├── sqlite_utils.py          # 安全分块执行
│   └── state_store.py           # state.json 管理
└── api/                         # FastAPI HTTP API
    ├── main.py
    ├── deps.py
    ├── routes_repo.py
    ├── routes_symbols.py
    ├── routes_graph.py
    └── routes_context.py
```

---

*报告结束*
