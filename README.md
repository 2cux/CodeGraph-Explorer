# CodeGraph Explorer

Local-first code graph and MCP workflow layer for coding agents.

CodeGraph Explorer 帮助 Claude Code、Codex、Cursor 等编码 Agent 在读文件和改代码前，先通过本地代码图理解符号、调用关系、影响范围和测试覆盖信号。

它是一个纯后端、MCP-native、local-first 的代码图系统：

- 不带 web dashboard
- 不依赖 SaaS 后端
- 不默认上传仓库源码
- 核心索引、本地 SQLite、MCP server、CLI 都在本地运行

## 为什么需要 CodeGraph Explorer？

很多 Agent 在进入任务时会直接 `Glob` / `Grep` / `Read`。这对小改动可以工作，但在这些场景里很容易失焦：

- 跨文件重构
- 共用类型或公共 API 修改
- route / service 影响分析
- 测试覆盖审计
- 模块职责解释和上下文建立

CodeGraph Explorer 先给 Agent 一个结构化入口，让它先问：

- 这个符号在哪里？
- 谁调用它？
- 改它会影响哪些文件和测试？
- 哪些 production symbols 缺少测试信号？
- 这个模块大概负责什么？
- 当前索引是否可信、是否过期？

准确的说法不是“完全替代 Read/Grep”，而是：

> CodeGraph helps agents start with structure and impact before falling back to targeted source reads.

## Quick Start

只保留源码安装路径，不使用 `npm` / `npx` / `curl` / `irm`。

### 1. 安装 CodeGraph Explorer

```bash
git clone https://github.com/2cux/CodeGraph-Explorer.git
cd CodeGraph-Explorer
pip install -e "backend[mcp,watch]"
```

### 2. 在目标项目初始化索引

```bash
cd /path/to/your-project
codegraph init
codegraph doctor
```

### 3. 配置 MCP

```bash
codegraph configure all
```

如果你明确需要覆盖已有配置，可使用：

```bash
codegraph configure all --force
```

这不是必需项，只在你确认需要重写已有配置时再使用。

### 4. 更新

```bash
cd CodeGraph-Explorer
git pull
pip install -e "backend[mcp,watch]"
codegraph configure all --force
codegraph doctor
```

## MCP Profiles

CodeGraph Explorer 提供四种 MCP tool profile，通过环境变量控制 Agent 看到的工具面：

```bash
# 推荐默认 (6 个高层工具 — 适合普通编码 Agent)
CODEGRAPH_MCP_PROFILE=agent

# 高级用户 (13 个稳定工具 — 包含底层 graph primitives)
CODEGRAPH_MCP_PROFILE=full

# Harness 自动化 (4 个 harness 工具 — run/status/artifacts)
CODEGRAPH_MCP_PROFILE=harness

# 开发调试 (17 个全部工具 — full + harness)
CODEGRAPH_MCP_PROFILE=debug
```

| Profile | Tools | 用途 |
|---|---|---|
| `agent` | 6 | 推荐默认 — 普通编码 Agent 高频工具 |
| `full` | 13 | 高级用户 — 手动图探索、深层调用链分析 |
| `harness` | 4 | Harness 自动化 — run/status/artifacts 查询 |
| `debug` | 17 | CodeGraph 开发调试 — full + harness |

- 未设置 `CODEGRAPH_MCP_PROFILE` 时默认使用 `agent` profile。
- 未知 profile 值 fallback 到 `agent` 并输出 stderr warning。
- `agent` 和 `full` profile 不暴露 harness tools。
- `codegraph configure all` 默认写入 `agent` profile。
- 需要完整工具时显式设置 `CODEGRAPH_MCP_PROFILE=full`。
- 需要 harness 自动化时显式设置 `CODEGRAPH_MCP_PROFILE=harness`。

### Agent Profile 工具列表

| Tool | 用途 |
|---|---|
| `codegraph_repo_status` | 检查索引新鲜度 |
| `codegraph_find` | 定位 symbol/class/function/route — 不要用于 impact/refactor |
| `codegraph_explain` | 解释 symbol/file — 读源码前理解"这做了什么" |
| `codegraph_pre_edit_check` | 编辑/重构/修改前检查影响面 |
| `codegraph_coverage_gaps` | 测试覆盖缺口审计 (heuristic graph signal) |
| `codegraph_build_context_pack` | 大范围任务上下文 — scan/deepen/impact 模式 |

### Entry Routing (入口选择)

| 任务 | 工具 |
|---|---|
| Need to locate a symbol/file? | `codegraph_find` |
| Need to understand what code does? | `codegraph_explain` |
| Need to edit/refactor/change code? | `codegraph_pre_edit_check` |
| Need to find missing tests? | `codegraph_coverage_gaps` |
| Need broader task context? | `codegraph_build_context_pack` |
| Need run artifacts / debug Harness? | 使用 `harness` or `debug` profile |

## Workflow-first：让 Agent 先用 CodeGraph

MCP 工具本身是被动的，Agent 不一定会自动优先使用它们。CodeGraph Explorer 提供可选 workflow commands，让用户显式进入 CodeGraph-first 流程。

安装 Claude Code workflow commands：

```bash
codegraph configure workflows --agent claude
```

会生成这些 Markdown workflow 文件：

```text
.claude/commands/codegraph-impact.md
.claude/commands/codegraph-test-audit.md
.claude/commands/codegraph-explain.md
.claude/commands/codegraph-find.md
```

使用方式：

```text
/codegraph-impact
/codegraph-test-audit
/codegraph-explain
/codegraph-find
```

| Command | 用途 |
|---|---|
| `/codegraph-impact` | 修改共用类型、route、service、公共 API 前先看影响范围 |
| `/codegraph-test-audit` | 查找缺少测试信号的 production symbols / files |
| `/codegraph-explain` | 在读完整源码前理解 symbol 或 file |
| `/codegraph-find` | 查找函数、类、方法、route、service，并决定下一步 |

这些 command 文件的边界很明确：

- 是纯 Markdown workflow 文件
- 不修改源码
- 不安装 hook
- 不创建 dashboard
- 不调用外部服务

## Deterministic Workflow CLI

当 MCP 不可用，或你想在 hook / CI / 脚本里稳定复用同一套逻辑时，可以直接使用 workflow CLI。

### 已实现

```bash
codegraph workflow impact --files backend/codegraph/workflow.py --change-type refactor
codegraph workflow test-audit --paths src/** --types function,method
codegraph workflow explain --symbol MemoryService
codegraph workflow find login
```

这些命令是确定性的 CLI 入口，适合作为 MCP fallback，也适合作为本地自动化的稳定执行目标。

## Harness

CodeGraph Harness 是内部 workflow 执行框架，让复杂代码分析任务变得**稳定、可追踪、可复现**。

每个 Harness run 自动记录：

- **结构化 input/output** — 输入参数和输出结果以 JSON 持久化
- **执行状态** — created → running → succeeded/failed，完整生命周期追踪
- **事件日志** — 关键步骤的 timestamped events
- **报告产物 (artifacts)** — JSON 报告和 Markdown 报告自动生成并落盘
- **失败诊断** — 异常时的完整 traceback 和 error context

Harness 使 workflow（impact、test-audit、explain、find）从一次性调用变成可审计的执行单元。CLI `codegraph workflow` 和 MCP `codegraph_harness_run` 共享同一执行引擎，保证输出一致性。

## Optional pre-commit impact hook

如果你希望在提交前做一次 warning-only 的本地影响检查，可以安装可选 pre-commit hook：

```bash
codegraph configure git-hook --pre-commit-impact
```

它会读取 staged files，并调用：

```bash
codegraph workflow impact --files <staged files> --change-type unknown --format markdown
```

默认行为：

- warning only，不阻塞 commit
- 不运行测试
- 不修改文件
- 不覆盖已有 hook，除非显式使用 `--force`

如需覆盖已有 hook：

```bash
codegraph configure git-hook --pre-commit-impact --force
```

详情见 [docs/git-hooks.md](docs/git-hooks.md)。

## MCP Tools

`coverage_gaps` 这里指的是基于代码图推断的 test signal，不是 runtime line coverage。

| Tool | 用途 |
|---|---|
| `codegraph_repo_status` | 检查项目根、索引 freshness、健康状态与建议动作 |
| `codegraph_repo_summary` | 获取仓库概览、语言分布、测试覆盖信号摘要 |
| `codegraph_find` | 一步完成 symbol search + 基础详情 |
| `codegraph_explain` | 基于代码图和 evidence 解释 symbol / file |
| `codegraph_pre_edit_check` | 改代码前检查 planned files / symbols 的影响 |
| `codegraph_get_impact` | 查询某个 symbol 的影响范围 |
| `codegraph_get_neighbors` | 查看某个 symbol 周边关系 |
| `codegraph_coverage_gaps` | 查找缺少测试信号的 production symbols / files |
| `codegraph_build_context_pack` | 构建 scan / deepen / impact 模式上下文包 |

## Verification

### MCP Profile A/B — Fresh Claude Code Session

在未见过 CodeGraph 代码的 fresh session 中，`agent` profile（6 个高层工具）的表现：

| 指标 | 结果 |
|---|---|
| MCP Start Rate | 100% — Agent 始终优先使用 CodeGraph |
| Wrong Entry Rate | 0% — 每次都选对了高层工具 |
| Broad Search Before MCP | 0% — 从未先用 rg/grep/glob 再补 CodeGraph |
| Task Success | 100% — 全部 6 类任务完成 |

对比 `without_codegraph` baseline：6/6 任务以 broad `rg` 起步。CodeGraph 将 broad search 从 100% 降到了 0%。

> **Scope:** 以上数据来自 fresh Claude Code session。Codex / Cursor 的跨 Agent 验证尚未完成。

### MCP Architecture — Direct Fast Path + Harness Workflow Path

CodeGraph 的 MCP 架构区分两条调用路径：

| 路径 | 用途 | 典型延迟 (p95) |
|---|---|---|
| **Direct MCP fast path** | 高频 Agent 调用 — find, explain, pre_edit_check | ~185ms（`codegraph_find` ~132ms） |
| **Harness workflow path** | 报告生成、artifacts、审计、调试 | 取决于 workflow 复杂度 |

- Direct MCP 工具直接查询本地索引，无额外持久化开销——适合 Agent 每步决策。
- Harness workflow 生成结构化报告（JSON + Markdown）、记录 run state、写入 artifacts——适合需要审计追踪或确定性输出的场景。
- `workflow.find` 的 MCP compact path 经优化后 p95 从约 7.2s 降至约 0.83s（88% 下降），保持 artifact 输出但不展开逐结果 heavy enrichment。

### Release Gate

默认 `agent` profile 上线前，8 项 release gate 全部通过：

| Gate | 状态 |
|---|---|
| 默认 profile = agent | ✅ |
| agent profile wrong_entry_tool_rate < 20% | ✅ (0%) |
| agent profile broad_search_before_mcp ≈ 0% | ✅ (0%) |
| agent profile immediate_fallback_after_mcp ≈ 0% | ✅ (0%) |
| agent profile task_success ≥ full/debug | ✅ (100%) |
| workflow.find compact p95 ≤ 2000ms | ✅ (829ms) |
| 核心回归测试通过 | ✅ (103/103) |
| 未删除任何工具和代码 | ✅ |

详细报告见 [docs/mcp-default-profile-release-readiness.md](docs/mcp-default-profile-release-readiness.md)。

## Backend-only and local-first

CodeGraph Explorer does not ship a web dashboard.
It does not require a SaaS backend.
It does not upload your repository by default.
The core index is local.
The MCP server and CLI run locally.

关于后续 LLM enrichment，当前不写成已内置 provider。规划方向是：

> Planned: Agent-side zero-config enrichment
>
> Future enrichment is designed to run through the user's coding agent workflow, not through a mandatory CodeGraph-hosted LLM API. CodeGraph will prepare bounded inputs, validate agent-generated JSON, and import local metadata.

## Agent 使用建议

CodeGraph MCP 安装完成后，Agent 不一定会自动优先使用它。Agent 仍然可能默认使用 Read / Grep / Glob。

如果希望 Agent 在某个目标项目里优先调用 CodeGraph MCP，需要把下面的提示块复制到目标项目的规则文件中。这里说的是目标项目，不是 CodeGraph Explorer 仓库本身。

### 目标位置

| Agent | 文件 |
|---|---|
| Claude Code | `CLAUDE.md` |
| Cursor | `.cursor/rules/codegraph.mdc` |
| 其他 Agent | `AGENTS.md` |

### CodeGraph Usage

```markdown
## CodeGraph Usage

This repository is indexed by CodeGraph.

Before code exploration, bug fixing, refactoring, feature implementation, or impact analysis, use CodeGraph MCP before grep/glob/read-heavy exploration.

Start with `codegraph_build_context_pack` for larger tasks.

Use:
- `codegraph_repo_summary` to understand repository structure.
- `codegraph_search_symbols` to find functions, classes, methods, routes, and entry points.
- `codegraph_get_neighbors` to inspect relationships around a symbol.
- `codegraph_get_callers` and `codegraph_get_callees` instead of grep for call chains.
- `codegraph_get_impact` before modifying shared code.

Use `Read` only when exact source text is needed.
```

几点边界需要明确：

- 这个提示块不会自动写入任何文件，需要手动复制
- 它是建议性的，不是要求 Agent 必须使用 CodeGraph 的机制
- 它帮助 Agent 更早进入结构化导航，但 does not automatically replace Read/Grep

## Roadmap

### 近期

- Better index health diagnostics: dropped-edge categories, top examples, auto-correction report.
- Better search ranking: production entry boost, test-file penalty, named seed injection.
- Better sufficiency: evidence, confidence, file-level staleness, targeted snippets.
- Better workflow follow-through: required next steps after find / impact / test-audit.
- Better shell compatibility for workflow paths on PowerShell.

### 后续

- Agent-side zero-config enrichment.
- Dynamic dispatch heuristics for callbacks, events, React, middleware.
- Non-code architecture files: Dockerfile, CI, package config, SQL, GraphQL, Terraform.
- More A/B evaluation gates.

## Known Issues

- Some Java / TypeScript tree-sitter dependency failures may still appear in the full backend test suite depending on local parser setup.
- High dropped-edge ratio should be inspected with `codegraph doctor`; fine-grained diagnostics are being improved.
- PowerShell wildcard expansion for workflow paths needs better handling.
- Flow tracing may still fall back to targeted grep when the current graph lacks enough caller/import evidence.

## 文档

| 文档 | 说明 |
|---|---|
| [docs/mcp-tools.md](docs/mcp-tools.md) | MCP 工具说明、Profile 体系、入口路由表 |
| [docs/mcp-default-profile-release-readiness.md](docs/mcp-default-profile-release-readiness.md) | 默认 agent profile 上线 Release Gate |
| [docs/profile-ab-report.md](docs/profile-ab-report.md) | MCP Profile A/B 验证报告 |
| [docs/workflow-find-optimization-report.md](docs/workflow-find-optimization-report.md) | workflow.find MCP 性能优化报告 |
| [docs/git-hooks.md](docs/git-hooks.md) | `pre-commit-impact` hook 的安装、覆盖和备份行为 |
| [docs/benchmark.md](docs/benchmark.md) | benchmark 与 regression gate |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | 当前语言/框架限制 |

## License

MIT
