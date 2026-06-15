# Agent Adoption P0 Test

> P0 效果验证文档：验证 `next_recommended_tools` 和 `codegraph_session` 是否真正提升了 Agent 持续使用 MCP 的行为。

## 背景

P0 的核心假设是：在每个成功 MCP 响应中同时放入"下一步建议"和"本轮 MCP 使用状态"，可以降低 Agent 的选择成本（choice paralysis）和遗忘问题（forgetting）。

- **`next_recommended_tools`**: 告诉 Agent 当前结果后应该调用哪个 CodeGraph 工具
- **`codegraph_session`**: 每次响应携带本轮使用状态，形成轻量 priming 效应

## 目标

验证 Agent 在第一次调用 CodeGraph 后，是否会继续顺着 `next_recommended_tools` 调用第二个、第三个 CodeGraph 工具，而不是立刻回到 Read / Grep / Glob。

## 前置条件

```bash
cd <target-project>
codegraph init
codegraph doctor
```

确认：

- [ ] MCP Server 已连接到 Agent（Claude Code / Cursor）
- [ ] `codegraph doctor` 输出 `symbols > 0`
- [ ] `codegraph doctor` 输出 `index_health: ok`
- [ ] `codegraph_repo_status` 返回 `recommended_action: use_codegraph`
- [ ] `project_root` 指向正确的项目
- [ ] 目标项目的 `CLAUDE.md` 或 `.cursor/rules/codegraph.mdc` 已放入 CodeGraph Usage 提示块

## 验证清单

对每个测试任务执行后，填写以下表格：

| 测试任务 | 首次 MCP 工具 | next_recommended_tools 是否出现 | codegraph_session 是否出现 | 是否继续调用第二个 MCP | 第二个 MCP 工具 | 是否回退 Grep/Read | 备注 |
|---|---|---|---|---|---|---|---|
| 1: 代码理解 | | | | | | | |
| 2: Bug Fix | | | | | | | |
| 3: 引用查询 | | | | | | | |

## 判断标准

### ✅ 有效

Agent 至少连续调用 2 个 CodeGraph tools，然后再按需 Read 精确源码。

例：
```
codegraph_build_context_pack → codegraph_get_neighbors → codegraph_get_impact → Read（精确文件）
```

### ⚠️ 部分有效

Agent 调用 1 个 CodeGraph tool，但没有 follow `next_recommended_tools` 的推荐。

例：
```
codegraph_search_symbols → Read（手动查看找到的文件）
codegraph_find → Read（直接跳到读文件）
```

### ❌ 无效

Agent 只调用一次或完全不用 CodeGraph，继续主要依赖 Grep / Read / Glob。

例：
```
Grep → Glob → Read → Read → Read（完全不碰 MCP）
```

## 测试任务 1：代码理解

### 任务描述

让 Agent 执行以下 prompt：

```text
Before reading files manually, use CodeGraph to understand how MemoryService
works and follow the recommended next tools.
```

### 观察记录

| 项目 | 记录 |
|---|---|
| 是否先调用 `codegraph_build_context_pack`、`codegraph_find` 或 `codegraph_search_symbols` | |
| 是否继续调用 `codegraph_get_neighbors` | |
| 是否继续调用 `codegraph_get_impact` | |
| 第二个 MCP 调用是否匹配 `next_recommended_tools` 推荐 | |
| 是否直接回退 Read / Grep | |
| Read 是否发生在 CodeGraph 推荐之后 | |

### 预期行为

```
codegraph_build_context_pack("MemoryService")
  → next_recommended_tools: [get_neighbors, get_impact]
  → Agent 调用 get_neighbors
  → next_recommended_tools: [get_impact]
  → Agent 调用 get_impact
  → 然后按需 Read 精确文件
```

## 测试任务 2：Bug Fix

### 任务描述

让 Agent 执行以下 prompt：

```text
Before editing, use CodeGraph to inspect the likely entry points,
dependencies, and impact for this bug fix: "login returns 500 when
password contains special characters".
```

### 观察记录

| 项目 | 记录 |
|---|---|
| 是否调用 `codegraph_build_context_pack`、`codegraph_find` 或 `codegraph_search_symbols` | |
| 是否调用 `codegraph_get_neighbors` / `codegraph_get_callers` / `codegraph_get_callees` | |
| 是否调用 `codegraph_get_impact` | |
| 是否因为 source snippets 不足而 Read | |
| Read 是否发生在 CodeGraph 推荐之后 | |
| 第二个 MCP 调用是否匹配 `next_recommended_tools` 推荐 | |

### 预期行为

```
codegraph_build_context_pack("fix login 500 error")
  → entry_points + source_snippets
  → next_recommended_tools: [get_neighbors, get_impact]
  → Agent 调用 get_neighbors 查看 login 周边关系
  → Agent 调用 get_impact 评估修改影响
  → Read 精确源码行
```

## 测试任务 3：引用查询

### 任务描述

让 Agent 执行以下 prompt：

```text
Use CodeGraph to find who calls <symbol> and follow the recommended
next tools before using grep.
```

（将 `<symbol>` 替换为项目中一个已知被多处调用的函数）

### 观察记录

| 项目 | 记录 |
|---|---|
| 是否调用 `codegraph_find`、`codegraph_search_symbols` 或 `codegraph_get_callers` | |
| 是否 follow `next_recommended_tools` | |
| 是否仍然 grep | |
| grep 是否发生在 CodeGraph 查询之后 | |

### 预期行为

```
codegraph_get_callers("<symbol>")
  → callers list
  → next_recommended_tools: [get_impact]
  → Agent 调用 get_impact 查看影响
  → 不再 grep
```

## 测试任务 4：符号解释（Explain Symbol）

### 任务描述

让 Agent 执行以下 prompt：

```text
Use codegraph_explain to understand what <symbol> does before
reading the file. Follow the recommended next tools.
```

### 观察记录

| 项目 | 记录 |
|---|---|
| 是否调用了 `codegraph_explain` | |
| explanation 是否包含 summary / confidence / basis | |
| implementation_signals 是否提供了有用信息 | |
| 是否 follow `next_recommended_tools` 调用了 `codegraph_get_neighbors` | |
| Read 是否发生在 CodeGraph 之后 | |

### 预期行为

```
codegraph_explain(symbol="<symbol>")
  → explanation.summary + implementation_signals + evidence
  → next_recommended_tools: [get_neighbors]
  → Agent 调用 get_neighbors
  → 然后按需 Read
```

## 测试任务 5：文件解释（Explain File）

### 任务描述

让 Agent 执行以下 prompt：

```text
Use codegraph_explain to get an overview of <file> before
reading it. Follow the recommended next tools.
```

### 观察记录

| 项目 | 记录 |
|---|---|
| 是否调用了 `codegraph_explain(file=...)` | |
| primary_symbols 是否列出了主要符号 | |
| likely_role 是否有意义 | |
| 是否 follow `next_recommended_tools` 调用了 `codegraph_search_symbols` | |

### 预期行为

```
codegraph_explain(file="<file>")
  → primary_symbols + likely_role + implementation_signals
  → next_recommended_tools: [search_symbols]
  → Agent 搜索关键符号
  → 然后按需 Read
```

## P0 字段验证

对所有成功 MCP 响应进行结构化检查：

| 检查项 | 通过 | 备注 |
|---|---|---|
| 所有成功响应包含 `next_recommended_tools` | | |
| 所有成功响应包含 `codegraph_session` | | |
| `next_recommended_tools` 最多 3 个 | | |
| 每个推荐包含 `tool` 和 `reason` | | |
| `reason` 不为空且非泛泛文案 | | |
| `codegraph_session` 包含 `tools_called_this_session` | | |
| `codegraph_session` 包含 `most_used_tool` | | |
| `codegraph_session` 包含 `hint` | | |
| `search_symbols` 无结果时不推荐 `get_symbol` | | |
| `repo_status` 为 `run_init` 时不推荐图查询 | | |
| `repo_status` 为 `refresh_index` 时不推荐图查询 | | |
| `repo_status` 为 `check_project_root` 时不推荐图查询 | | |
| `get_impact` 无结果时不机械推荐 `get_neighbors` | | |
| 不出现 `get_neighbors → get_impact → get_neighbors` 循环 | | |

## 回归检查

| 检查项 | 通过 | 备注 |
|---|---|---|
| 所有现有测试通过 (`pytest backend/tests/`) | | |
| Benchmark gate 不退化 | | |
| MCP Server 正常启动 | | |

## 常见问题

### Agent 完全不 follow `next_recommended_tools`

可能原因：
1. Agent 有自己的工具选择策略，不一定会遵循建议
2. 推荐的工具在当前上下文中不适用
3. `reason` 文字不够有说服力

**对策**：检查 `reason` 是否具体说明了"为什么现在调用这个工具"和"它替代了什么手动步骤"。

### Agent 只调用一次就回退

可能原因：
1. `codegraph_session` 的 `hint` 不够有推动力
2. source snippets 不够，Agent 被迫 Read

**对策**：检查 `hint` 文字是否与当前 tool 匹配。

### 循环推荐

可能原因：
1. `get_neighbors` → `get_impact` → `get_neighbors` 循环
2. 推荐列表没有随上下文变化

**对策**：已修复 —— `get_impact` 有结果后不再推荐 `get_neighbors`。

## `codegraph_coverage_gaps` 使用验证

### 任务描述

让 Agent 执行以下 prompt：

```text
Use CodeGraph to find which production symbols lack test coverage, 
then follow the recommended next tools before reading test files.
```

### 预期行为

```
codegraph_coverage_gaps()
  → summary: production_symbols_checked, symbols_without_test_signal, etc.
  → symbols_without_tests: [(symbol, file, line, reason), ...]
  → next_recommended_tools: [get_neighbors, get_impact]
  → Agent 调用 get_neighbors 查看 uncovered symbol 周边关系
  → 然后按需 Read 精确源码或测试文件
```

### 判断标准

- ✅ Agent 一次调用就拿到覆盖缺口列表，不再逐个符号调用 get_neighbors
- ✅ Agent follow next_recommended_tools 中的 get_neighbors 或 get_impact
- ✅ Agent 没有回退到 Glob / Read 扫描
- ❌ Agent 将 coverage_gaps 结果理解为 line coverage

## `codegraph_pre_edit_check` 使用验证

### 任务描述

让 Agent 执行以下 prompt：

```text
Before editing these files, use CodeGraph to check the pre-edit impact,
then follow the recommended next tools before manually reading or grepping.
```

### 预期行为

```
codegraph_pre_edit_check(files="src/server.ts", change_type="refactor")
  → planned_files, planned_symbols
  → impact_summary: risk_level, confidence, summary
  → affected_callers, affected_files, affected_tests
  → recommended_checks: [read, test]
  → next_recommended_tools: [get_neighbors, get_impact]
  → Agent follow 推荐调用 get_neighbors 或 get_impact
  → 然后按需 Read 精确文件
```

### 判断标准

- ✅ Agent 在编辑前主动调用 `codegraph_pre_edit_check`，而不是跳过影响分析直接编辑
- ✅ Agent follow `next_recommended_tools` 中的推荐工具
- ✅ Agent 没有回退到手工 grep 或盲目 Read
- ✅ Agent 理解 `risk_level` 含义（high/medium 时更谨慎）
- ❌ Agent 将 `codegraph_pre_edit_check` 与 `codegraph_get_impact` 混淆
- ❌ Agent 在 `risk_level: unknown` 时仍当作 fully informed 继续编辑

## 更新记录

| 日期 | 变更 |
|---|---|
| 2026-06-15 | 新增 `codegraph workflow impact` CLI 工作流作为 MCP fallback |
| 2026-06-14 | 新增 `codegraph_pre_edit_check` 作为任务级编辑前影响检查工具 |
| 2026-06-14 | 新增 `codegraph_find` 作为首选入口工具（搜索+详情融合） |
| 2026-06-14 | 新增 `codegraph_coverage_gaps` 验证任务 |
| 2026-06-12 | 初始版本：P0 验证文档，含 3 个测试任务、验证表格、判断标准 |

## Claude Code Workflow Commands 验证

### 安装

```bash
codegraph configure workflows --agent claude
```

### 验证清单

| 检查项 | 通过 | 备注 |
|---|---|---|
| `.claude/commands/` 目录已创建 | | |
| `codegraph-impact.md` 已安装且内容包含 `codegraph_pre_edit_check` | | |
| `codegraph-test-audit.md` 已安装且内容包含 `codegraph_coverage_gaps` | | |
| `codegraph-explain.md` 已安装且内容包含 `codegraph_explain` | | |
| `codegraph-find.md` 已安装且内容包含 `codegraph_find` | | |
| 文件不包含 `CODEGRAPH_PROJECT_ROOT` 硬编码 | | |
| 文件不包含当前项目绝对路径 | | |
| 再次运行不覆盖已有文件（跳过提示） | | |
| `--force` 可以覆盖已有文件 | | |
| 文件内容不引用 frontend / dashboard / browser UI | | |
| 文件内容不引用 git hook | | |
| 所有现有测试通过 (`pytest backend/tests/`) | | |

## Optional Git pre-commit impact hook 验证

### 安装

```bash
codegraph configure git-hook --pre-commit-impact
```

### 验证清单

| 检查项 | 通过 | 备注 |
|---|---|---|
| `.git/hooks/pre-commit` 文件已创建 | | |
| hook 文件包含 `codegraph workflow impact` | | |
| hook 文件可执行（Unix） | | |
| 非 Git repo 下返回可读错误 | | |
| 已有 pre-commit hook 且无 `--force` 时不覆盖 | | |
| 已有 pre-commit hook 且 `--force` 时备份旧 hook (`.codegraph.bak`) | | |
| `--force` 后写入新 hook | | |
| 命令不修改 MCP config | | |
| 命令不自动运行测试 | | |
| 命令不自动 `codegraph init` | | |
| 命令不新增前端依赖 | | |
| `docs/git-hooks.md` 存在并说明 warning-only 行为 | | |
| 所有现有测试通过 (`pytest backend/tests/`) | | |

### Hook 行为验证

| 检查项 | 通过 | 备注 |
|---|---|---|
| staged files 为空时 hook exit 0 | | |
| `codegraph workflow impact` 失败时 hook 默认 exit 0 | | |
| hook 不阻塞 commit（始终 exit 0） | | |
| hook 不写文件到 `.codegraph/reports/` | | |
| hook 不调用外部服务 | | |

### 工作流集成验证

安装后，在 Git repo 中测试：

```bash
# 模拟一次有 staged files 的 commit
echo "test" > test_file.py
git add test_file.py
git commit -m "test: verify pre-commit hook"

# 预期：hook 运行 impact check，输出 Markdown 到终端，commit 正常完成
# 如果 codegraph workflow impact 不存在，hook 输出提示但不阻塞
```

清理：

```bash
git reset HEAD~1
rm test_file.py
```

### 工作流验证

安装后，在 Claude Code 中测试以下 slash command：

#### `/codegraph-impact`

```
/codegraph-impact <symbol>
```

预期行为：
1. Agent 调用 `codegraph_repo_status`
2. Agent 调用 `codegraph_pre_edit_check` 或 `codegraph_get_impact`
3. Agent 仅在 CodeGraph 返回结果后 Read 具体文件
4. Agent 不先 Grep/Glob

#### `/codegraph-test-audit`

预期行为：
1. Agent 调用 `codegraph_repo_status`
2. Agent 调用 `codegraph_coverage_gaps`
3. Agent 按需调用 `codegraph_explain` 或 `codegraph_get_neighbors`
4. Agent 不先 Glob 测试文件

#### `/codegraph-explain`

```
/codegraph-explain <symbol_or_file>
```

预期行为：
1. Agent 调用 `codegraph_repo_status`
2. Agent 调用 `codegraph_explain`
3. Agent 按需调用 `codegraph_get_neighbors`
4. Agent 不先 Read 全文件

#### `/codegraph-find`

```
/codegraph-find <name>
```

预期行为：
1. Agent 调用 `codegraph_repo_status`
2. Agent 调用 `codegraph_find`
3. Agent 调用 `codegraph_get_neighbors` 查看关系
4. Agent 不先 Grep
