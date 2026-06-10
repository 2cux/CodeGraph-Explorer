# Agent Adoption Test

## 目标

验证 Claude Code / Cursor 是否在真实任务中调用 CodeGraph MCP，而不是只使用 grep/read。

## 步骤

### 1. 在目标项目初始化索引

```bash
cd your-project
codegraph init
codegraph doctor
```

### 2. 确认索引正常

确认 `codegraph doctor` 输出中：
- `symbols > 0`
- `index_health` 为 `ok`
- `index_status` 为 `fresh`

### 3. 放入 CodeGraph Usage 提示块

把 CodeGraph Usage 提示块复制到目标项目：

| Agent | 位置 |
|-------|------|
| Claude Code | 目标项目 `CLAUDE.md` |
| Cursor | 目标项目 `.cursor/rules/codegraph.mdc` |
| Other agents | 目标项目 `AGENTS.md` |

提示块内容参考 README 的「让 Agent 优先使用 CodeGraph」部分。

### 4. 开启新的 Agent Session

重启 Claude Code 或 Cursor，确保新 session 加载了步骤 3 的规则文件。

### 5. 提交一个真实任务

向 Agent 提交一个真实任务，例如：

```text
Before editing, inspect this project using CodeGraph and identify the relevant entry points.
```

任务需要足够复杂，使 Agent 有机会使用 CodeGraph 工具。

### 6. 任务完成后询问 Agent

任务完成后，在同一个 session 中追问：

```text
本轮是否调用了 CodeGraph MCP？调用了哪些工具？
```

## 记录结果

| 工具 | 是否调用 | 备注 |
|------|---------|------|
| `codegraph_build_context_pack` | | |
| `codegraph_repo_summary` | | |
| `codegraph_search_symbols` | | |
| `codegraph_get_neighbors` | | |
| `codegraph_get_impact` | | |
| `codegraph_repo_status` | | |
| 是否仍然只使用 Grep / Read / Glob | | |

## 常见问题

### Agent 完全没有调用 CodeGraph

可能原因：

1. MCP 配置未在编辑器重启后生效 — 检查 MCP 面板状态
2. CodeGraph Usage 提示块未放入目标项目的规则文件
3. 目标项目的 `CLAUDE.md` 中有冲突指令
4. 任务的复杂度过低，Agent 认为不需要 CodeGraph

### 建议的任务类型

以下任务更容易触发 CodeGraph 工具使用：

| 任务 | 预期触发工具 |
|------|-------------|
| 分析某个功能的调用链 | `search_symbols` → `get_callees` / `get_neighbors` |
| 修改共享代码前评估影响 | `get_impact` |
| 初次进入陌生代码库 | `repo_summary` → `search_symbols` |
| 大规模修改或重构 | `build_context_pack` → `get_neighbors` → `get_impact` |
