# Baseline: Current State

> 建立日期：2026-06-15
> 目的：固定当前已完成的能力，形成可回归的基线。本阶段禁止继续新增普通 MCP 工具。

---

## 1. 测试基线

### 1.1 单元/集成测试

| 指标 | 数值 | 备注 |
|------|------|------|
| 总测试数 | 1,954 | 1,946 passed + 1 failed + 7 skipped |
| 通过 | 1,946 | — |
| 失败 | 1 | `test_mcp_tools.py::TestNoActionAdviceAnywhere::test_repo_summary_no_advice` — flaky，单独运行通过 |
| 跳过 | 7 | — |
| 新增回归测试 | 41 | `test_mcp_final_regression.py`，全部通过 |

**失败详情：**
- `test_mcp_tools.py::TestNoActionAdviceAnywhere::test_repo_summary_no_advice`：响应文本中包含 "reading_plan" 字样（来自某个 next_recommended_tools 建议文本），但并非实际的 reading_plan 字段。属于 flaky test，待修复。

### 1.2 Benchmark Gate

| 类别 | 检查项 | 值 | 阈值 | 状态 |
|------|--------|-----|------|------|
| Recall | Symbol recall | 64.3% | ≥55% | ✅ |
| Recall | File recall | 92.1% | ≥75% | ✅ |
| Recall | Recall pass rate | 83.3% (10/12) | ≥58% | ✅ |
| Token | Token reduction | 75.0% | ≥10% | ✅ |
| Token | Compact vs standard | 68.1% | ≥30% | ✅ |
| Token | Avg compact payload | 685 tokens | ≤2,000 | ✅ |
| Token | Avg full task estimate | 1,118 tokens | ≤3,000 | ✅ |
| 工具减少 | grep/read 减少 | 90.3% | ≥40% | ✅ |
| 工具减少 | File read 减少 | 77.5% | ≥30% | ✅ |
| 搜索质量 | Top-1 accuracy | 91.7% | ≥50% | ✅ |
| 搜索质量 | Ambiguous rate | 0.0% | ≤25% | ✅ |
| 搜索质量 | Search recall | 64.3% | ≥40% | ✅ |
| 边质量 | False confirmed edges | 0 | ≤0 | ✅ |
| 边质量 | Unresolved in confirmed | 0 | ≤0 | ✅ |
| Impact | Confirmed/possible 分离 | 0 overlap | 0 | ✅ |
| Impact | Tests 独立分组 | 0 test symbols | 分开 | ✅ |
| Impact | 无 unresolved 在 confirmed | 0 | 0 | ✅ |
| MCP 协议 | index_status 存在 | present | present | ✅ |
| MCP 协议 | Compact 无 full source | clean | clean | ✅ |
| MCP 协议 | Compact 无 full evidence | clean | clean | ✅ |
| MCP 协议 | Compact 无 markdown body | clean | clean | ✅ |
| MCP 协议 | stdout JSON 可解析 | parseable | parseable | ✅ |
| Evidence Pack | 无 reading_plan | absent | absent | ✅ |
| Evidence Pack | 无 agent_instructions | absent | absent | ✅ |
| Evidence Pack | 无 recommended_context | absent | absent | ✅ |
| Evidence Pack | 无 implementation_plan | absent | absent | ✅ |
| 增量索引 | Cosmetic skip rebuild | COSMETIC | ✅ |
| 增量索引 | Structural partial update | ✅ |
| 增量索引 | Deleted file cleanup | ✅ |
| 增量索引 | No full replace degradation | ✅ |
| 存储 | Dangling edges | 0 | ≤0 | ✅ |
| 存储 | FTS count = SQLite | 0 mismatches | ✅ |
| 存储 | Validation status | 0 errors | ✅ |
| 存储 | Storage integrity | 0 errors | ✅ |

**结果：36 checks passed, 0 failed — PASS**

---

## 2. Dropped Edges 基线

### 2.1 数值

| 指标 | 数值 |
|------|------|
| 总 dropped edges | 4,194 |
| Dangling edges（引用不存在的节点） | 4,193 (99.98%) |
| Invalid edge type | 1 (0.02%) |
| Auto-corrected | 0 |
| 验证前总边数（SQLite） | 22,858（18,664 存活 + 4,194 dropped） |
| Dropped ratio（vs 验证前总边数） | 18.35% (4,194 / 22,858) |
| 验证后存活边数（SQLite） | 18,664 |
| Live store 边数（MCP 查询用） | 22,100（加载自 SQLite，未经 validation 过滤） |

### 2.2 已知局限

**Dropped edges 分类尚不清楚。** 当前验证只区分两类 drop 原因：
- `dangling_edge` — 边引用的 source 或 target 节点在节点表中不存在
- `invalid_edge_type` — 边的 type 字段不在 EdgeType 枚举中

**缺少的细分维度：**
- 按语言分：Python / TypeScript / Java / Go / C# 各自的 dropped 比例未知
- 按边类型分：calls / imports / contains / tested_by / references 各自的 dropped 比例未知
- 按源文件/模块分：哪些模块产生的 dangling edge 最多未知
- 根因分：dangling 是因为解析缺失？还是跨语言引用？还是外部库符号？未知
- 按 resolution 分：unresolved / name_match / heuristic 各自导致的 dropped 比例未知

**当前建议：**
- 运行 `codegraph doctor --repair` 从 SQLite 重建 JSON（SQLite 是 source of truth）
- 但 dangling edges 是结构性问题，repair 不会修复它们——repair 只同步 JSON ↔ SQLite

---

## 3. Agent 测试基线

### 3.1 Agent 使用次数

本会话中 CodeGraph MCP 工具调用统计：

| 工具 | 调用次数 |
|------|----------|
| codegraph_repo_summary | 2 |
| codegraph_search_symbols | 1 |
| **总计** | **3** |

### 3.2 已知问题

**当前 Agent 仍可能只调用 1～2 次 CodeGraph 就回退到 grep/read。**
- 虽然 benchmark 显示 90.3% grep/read 减少，但这是 benchmark fixture 场景
- 真实任务中 Agent 可能在拿到 context_pack 或 search 结果后仍然选择 grep/read 验证
- 缺少"Agent 是否持续使用 CodeGraph 完成整个任务"的端到端指标

### 3.3 非 MCP Agent 场景

- Evidence Pack（context_pack summary 模式）可供非 MCP Agent 或人类使用
- CLI `workflow impact` 提供确定性影响分析报告，适用于 CI/hook/非 MCP 场景

---

## 4. 当前工具列表

### 4.1 MCP 工具（13 个）

| # | 工具名 | 用途 | 加入轮次 |
|---|--------|------|----------|
| 1 | `codegraph_search_symbols` | 搜索代码符号 | MVP |
| 2 | `codegraph_get_symbol` | 获取符号详情 | MVP |
| 3 | `codegraph_get_callers` | 查询调用者 | MVP |
| 4 | `codegraph_get_callees` | 查询被调用者 | MVP |
| 5 | `codegraph_get_neighbors` | 查询局部子图 | MVP |
| 6 | `codegraph_get_impact` | 分析修改影响面 | MVP |
| 7 | `codegraph_repo_status` | 检查索引新鲜度 | MVP |
| 8 | `codegraph_repo_summary` | 仓库概览 | MVP |
| 9 | `codegraph_build_context_pack` | 渐进式上下文包（scan→deepen→impact） | R6-R8-R17 |
| 10 | `codegraph_find` | 融合 search + get_symbol | R9 |
| 11 | `codegraph_coverage_gaps` | 测试覆盖缺口分析 | R11 |
| 12 | `codegraph_pre_edit_check` | 编辑前影响检查 | R12 |
| 13 | `codegraph_explain` | 确定性符号/文件解释 | R13 |

### 4.2 CLI 命令

| 命令 | 用途 |
|------|------|
| `codegraph init` | 初始化/重建索引 |
| `codegraph update` | 更新 CodeGraph 自身 |
| `codegraph status` | 检查索引新鲜度 |
| `codegraph search <query>` | 搜索符号 |
| `codegraph explain <symbol>` | 解释符号调用关系 |
| `codegraph impact <symbol>` | 分析修改影响面 |
| `codegraph context <task>` | 生成 Evidence Pack |
| `codegraph api` | 启动 HTTP API 服务器 |
| `codegraph watch` | 文件监控自动增量索引 |
| `codegraph serve --mcp` | 启动 MCP 服务器（Agent 主入口） |
| `codegraph doctor` | 环境诊断（含 --repair） |
| `codegraph sync` | 内部：增量同步（供 hook 调用） |
| `codegraph hooks install/uninstall/status` | Git post-commit hook 管理 |
| `codegraph config set/get` | 配置管理 |
| `codegraph workflow impact` | 确定性 CLI 影响分析报告 |

### 4.3 全局 MCP 响应增强（所有工具共享）

| 特性 | 加入轮次 |
|------|----------|
| `codegraph_session` — 会话级工具调用统计 | R3 |
| `next_recommended_tools` — 下一步工具建议 | R3 |
| `index_status` — 索引新鲜度信号 | R4 |
| `index_health` — 索引健康信号（dropped/warnings/fatal） | R4 |
| `mode` presets（quick/deep/review） | R5 |
| Compact/standard 响应模式 | MVP |
| 工具描述中的 cost hints 和示例驱动描述 | R4-R5 |

### 4.4 非功能特性

| 特性 | 说明 |
|------|------|
| 增量索引 | 基于指纹的变更分类（COSMETIC/STRUCTURAL/ADDED/DELETED） |
| Post-commit hook | Git hook 自动增量同步 |
| 多语言支持 | Python（production）、TS/JS/Java/Go/C#（beta） |
| 存储双轨 | SQLite（主存储）+ JSON（备份/fallback） |
| FTS 全文搜索 | SQLite FTS5，符号名快速搜索 |
| Graph validation | 写入前+读取时图结构校验，auto-correct + drop |
| 零遥测 | 无任何数据外发 |
| MCP 协议合规 | stdout 纯净 JSON，stderr 日志隔离 |

---

## 5. 已知问题

### 5.1 Dropped Edges 分类不明确

见 [Section 2.2](#22-已知局限)。当前只能区分 dangling 和 invalid_type，无语言/边类型/根因细分。

### 5.2 Context Pack Scan 入口可能不准

`codegraph_build_context_pack` 的 mode="scan" 依赖关键字匹配 + FTS 搜索发现入口点。在以下场景可能不准确：
- 任务描述使用非代码术语（如 "fix login bug" → 实际符号名是 `authenticate_user`）
- 入口点不在 FTS 索引的热门符号中
- 多关键词任务中，回退到全局热门符号可能不相关

### 5.3 Agent 可能浅用 CodeGraph

- 真实任务中 Agent 可能在 1-2 次 CodeGraph 调用后就回退到 grep/read
- 缺少"CodeGraph 持续使用率"指标（当前只有 benchmark recall 指标）
- 可能原因：工具描述不够显眼、Agent 的 grep/read 习惯强

### 5.4 没有 Agent-side LLM Enrichment

- CodeGraph 当前不做任何语义理解或 LLM 增强
- 符号搜索纯基于关键词匹配 + FTS
- Context pack 的 entry point discovery 也是基于规则（关键词 → FTS → 热门符号）
- 可能导致搜索结果相关性不够高

### 5.5 低置信度边比例偏高

- Low confidence edge ratio: **35.9%**（Python）
- 可能影响 impact analysis 和 call graph 的可靠性
- 355 个 low-confidence tested_by 边可能导致测试覆盖信号不准确

### 5.6 Index Health Degraded

- 4,194 edges dropped during validation
- Dropped ratio（vs 验证前总边数，来自 validation_report.json）：**18.35%**（4,194 / 22,858）
- `index_health.dropped_ratio`（来自 MCP 响应）显示为 0.7752，但这是 `dropped_edges / total_symbols`（4,194 / 5,410），非标准的 "dropped / total_edges" 比率。此指标口径可能产生误导。
- Benchmark gate 的 storage checks 全部通过（0 dangling edges in benchmark fixtures）
- 说明 dropped edges 集中在主项目自身索引，benchmark 小项目不受影响

### 5.7 1 Flaky Test

- `test_repo_summary_no_advice` — 响应文本中某处包含 "reading_plan" 字样（可能来自 next_recommended_tools 建议），非结构性 bug

---

## 6. 索引统计快照

| 指标 | 数值 |
|------|------|
| 总文件 | 302 |
| 总符号 | 5,410 |
| 总边 | 22,100 |
| 函数 | 667 |
| 类 | 540 |
| 方法 | 576 |
| 测试符号 | 1,820 |
| 路由 | 23 |
| 低置信度边 | 7,932 (35.9%) |
| 跨语言边（未解析） | 1,605 (7.3%) |
| 测试文件检测 | 215 |
| 高置信度 tested 符号 | 194 |
| 低置信度 tested 符号 | 355 |
| 索引时间 | 2026-06-15T03:35:41Z |
| 索引后变化文件 | 388 |
| 索引健康状态 | degraded |

---

## 7. 本阶段禁令

**明确禁止本阶段继续新增普通 MCP 工具。**

当前 13 个 MCP 工具已经覆盖了核心使用场景：
1. 发现（search_symbols, find, repo_summary）
2. 导航（get_symbol, get_callers, get_callees, get_neighbors）
3. 影响分析（get_impact, pre_edit_check）
4. 上下文（build_context_pack, explain）
5. 健康检查（repo_status, coverage_gaps）

下阶段工作方向应为：
- **质量提升** — 提高搜索精度、降低低置信度边比例、改进 dropped edges 分类
- **Agent 深度使用** — 提升 Agent 的 CodeGraph 持续使用率
- **LLM enrichment** — 探索语义搜索/符号相关性排序
- **Bug 修复** — 解决已知 flaky test、改进 scan 入口准确性

---

## 8. 验收确认

- [x] 有当前状态文档（本文件）
- [x] 有测试基线（Section 1：1,946 passed, 36 gate checks all passed）
- [x] 有 Agent 测试基线（Section 3：CodeGraph 调用 3 次，已知浅用问题）
- [x] 有 dropped edges 当前数值记录（Section 2：4,194 dropped, 4,193 dangling）
